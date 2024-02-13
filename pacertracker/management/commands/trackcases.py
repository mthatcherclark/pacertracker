import os
import datetime
import timeit
import time
import re
import requests
import html
import uuid
import hashlib

from concurrent import futures
from functools import reduce
from bs4 import BeautifulSoup
from dateutil import parser
from dateutil.tz import gettz
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db.utils import IntegrityError, OperationalError

import pacertracker
from pacertracker.models import Court, Case, Entry
from pacertracker.search_indexes import CaseIndex

utc = datetime.timezone.utc

def requests_retry_session(
    retries=2,
    backoff_factor=0.1,
    session=None,
):
    # https://urllib3.readthedocs.io/en/latest/reference/urllib3.util.html
    # https://www.peterbe.com/plog/best-practice-with-retries-with-requests
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    return session

def download_feed(court, feeds_path):
    """
    Downloads court feeds
    """
    response = requests_retry_session().get(
        court.feed_url,
        timeout=30
    )
    
    with open('%s/%s - %s.xml' % (feeds_path, court.name, court.get_type_display()), 'w') as out:
        out.write(response.text)
    
    return None
    
def get_tzinfos():
    #Necessary for dateutil parser
    tzinfos = {'EDT': gettz("America/New York"),
                'CDT': gettz("America/Chicago"),
                'MDT': gettz("America/Denver"),
                'PDT': gettz("America/Los Angeles"),
                'EST': gettz("America/New York"),
                'CST': gettz("America/Chicago"),
                'MST': gettz("America/Denver"),
                'PST': gettz("America/Los Angeles"),
                'GMT': gettz("UTC"),
                }
                    
    return tzinfos

def get_case_type(case_number, court):
    """
    Gets the case type and returns it
    """
    if court.type == 'B':
        type = '3BK'
    elif court.type == 'A' or court.type == 'S':
        type = '4AP'
    elif court.type == 'M':
        type = '5MD'
    else:
        type = re.search('(?<=-)\w{1,4}(?=-)', case_number).group() # THIS IS NOT CATCHING TYPES THAT ARE NOT 2 CHARS
        #District Court cases with a "bk" as case type are multidistrict (civil) not bankruptcy
        if (type == 'cv' or type == 'mc' or type == 'ct' or type == 'dp' or type == 'md'
            or type == 'cm' or type == 'fp' or type == 'gd' or type == 'ml' or type == 'pf'
            or type == 'sw' or type == 'xc' or type == 'af' or type == 'de' or type == 'dj'
            or type == 'gp' or type == 'oe' or type == 'aa' or type == 'at' or type == 'adr'
            or type == 's1' or type == 'av' or type == 'wp' or type == '2255'
            or type == 'wf' or type == 's' or type == 'dcn' or type == 'ad' or type == 'w'
            or type == 'ds' or type == 'sp' or type == 'rd' or type == 'rj' or type == 'bk'
            or type == 'ma' or type == 'ra' or type == 'hcd' or type == 'DX' or type == 'BZ' 
            or type == 'AM' or type == 'AL' or type == 'DG' or type == 'GL' or type == 'PV' 
            or type == 'PP' or type == 'LV' or type == 'CB' or type == 'CM' or type == 'DS' 
            or type == 'UR' or type == 'LD' or type == 'FL' or type == 'EC' or type == 'DV' 
            or type == 'op' or type == 'ph' or type == 'BC' or type == 'sb' or type == 'rf'):
            type = '1CV'
        elif (type == 'cr' or type == 'mj' or type == 'po' or type == 'gj' or type == 'cb'
                or type == 'tp' or type == 'pt' or type == 'fj' or type == 'tk'
                or type == 'hc' or type == 'cn' or type == 'xr' or type == 'pr'
                or type == 'mw' or type == 'r' or type == 'sm' or type == 'm'
                or type == 'te' or type == 'mr' or type == 'mb'
                or type == 'mm' or type == '~gr' or type == 'y' or type == 'mj' 
                or type == 'wt'):
            type = '2CR'
        elif type == 'vc' or type == 'vv':
            type = '6VC'
        elif type == 'cg':
            type = '7CG'
        else:
            raise AttributeError
    return type


def get_entry_info(entry):
    """
    Gets the description, document number, website, and document id (if available)
    and returns them
    """
    entry_summary = html.unescape(entry.description.text).replace("'",'"')
    #Some bankruptcy cases have more than just a docket name. Capture that, too.
    if 'Trustee: ' in entry_summary:
        description = re.search('Trustee: .+(?=\])', entry_summary).group() + ']'
    else:
        description = re.search('(?<=\[).+(?=\])', entry_summary).group()
    
    number = re.search('(?<=">)\d+(?=</a>)', entry_summary)
    website = re.search('(?<=a href=").+(?=">)', entry_summary)
    
    if number and website:
        return description, int(number.group()), website.group()
    elif website:
        return description, None, website.group()
    else:
        return description, None, None


def save_everything(last_entries_saved, entries_to_save, total_entries_duplicate, total_cases, total_entries):
    #############
    # Save the cases and entries
    #############

    # Remove duplicate entry_ids, if any
    entry_ids = [x[11] for x in entries_to_save]
    indices_to_delete = [i for i, x in enumerate(entry_ids) if x in entry_ids[:i]]
    old_length = len(entries_to_save)
    entries_to_save = [x for i, x in enumerate(entries_to_save) if i not in indices_to_delete]
    entry_ids = [x[11] for x in entries_to_save]
    
    # Remove any entries already saved
    # We still believe this is is necessary due to some kind of race condition
    entries_to_save = [x for x in entries_to_save if x[11] not in last_entries_saved]
    total_entries_duplicate += old_length - len(entries_to_save)
    
    #entries_to_save.append((0 court, 1 title, 2 case_number, 3 name, 4 type, 5 is_date_filed, 
    #                        6 case_website, 7 description, 8 doc_number, 9 doc_website, 10 time_filed, 
    #                        11 entry_id, 12 case_id))
    
    if entries_to_save:
        # Find the entries that already exist
        returned_entries = list(Entry.objects.filter(id__in=entry_ids).select_related('case'
                                ).values_list('id', flat=True))
        
        # Eliminate any entry with identical field values
        indices_to_delete = [i for i, x in enumerate(entries_to_save) if x[11] in returned_entries]
        entries_to_save = [x for i, x in enumerate(entries_to_save) if i not in indices_to_delete]
        total_entries_duplicate += len(indices_to_delete)
        for x in entries_to_save:
            last_entries_saved.append(x[11])
        
        if entries_to_save:
            # Obtain unique list of cases and associated entries
            case_ids = [x[12] for x in entries_to_save]
            cases_to_save = [x for i, x in enumerate(entries_to_save) if x[12] not in case_ids[i + 1:]]
            
            # Begin saving cases by getting a list of cases already in the database
            saved_cases = []
            returned_case_dict = dict([(c.id, c) for c in Case.objects.filter(id__in=case_ids)])
            
            # Update the titles, names and numbers of cases if they are different
            # MIGHT WANT TO REPLACE ALL OF THIS WITH GET_OR_CREATE IF IT IS FASTER
            for case_to_update in cases_to_save:
                if case_to_update[12] in returned_case_dict: # The keys of returned_case_dict are ids
                    case = returned_case_dict[case_to_update[12]]
                    saved_cases.append(case)
                    if case.title != case_to_update[1]:
                        case.title = case_to_update[1]
                        case.number, case_name = case_to_update[2], case_to_update[3]
                        case.save(update_fields=['title', 'name', 'number'])
            
            # This is the best method for handling race conditions...
            # https://stackoverflow.com/questions/3522827/handling-race-condition-in-model-save/3523439#3523439
            while cases_to_save:
                try:
                    cases_to_save = [Case(court=x[0], title=x[1], website=x[6], number=x[2], name=x[3], type=x[4], 
                                     is_date_filed=x[5], id=x[12]) for x in cases_to_save 
                                     if x[12] not in returned_case_dict]
                    Case.objects.bulk_create(cases_to_save)
                    saved_cases.extend(cases_to_save)
                    total_cases += len(cases_to_save)
                    cases_to_save = None
                except IntegrityError:
                    time.sleep(.1)
                    print('IntegrityError with cases_to_save')
                    # The below has been commented out for now to see if we can skip it...
                    # returned_cases = list(Case.objects.filter(website__in=websites).values_list('website', flat=True))
                    # cases_to_save = [x for x in cases_to_save if x.website not in returned_cases]
                    Case.objects.bulk_create(cases_to_save)
                    saved_cases.extend(cases_to_save)
                    total_cases += len(cases_to_save)
                    cases_to_save = None
            
            #Save the entries
            for indice, new_entry in enumerate(entries_to_save):
                entries_to_save[indice] = Entry(case_id=new_entry[12], description=new_entry[7], number=new_entry[8], 
                                                website=new_entry[9], time_filed=new_entry[10],
                                                id=new_entry[11])
            
            Entry.objects.bulk_create(entries_to_save)
            total_entries += len(entries_to_save)
            
            # Get the ids of saved cases so you can update their updated_time
            case_ids = [x.id for x in saved_cases]
            while case_ids:
                try:
                    Case.objects.filter(id__in=case_ids).update(updated_time=datetime.datetime.utcnow().replace(tzinfo=utc))
                    case_ids = None
                except OperationalError:
                    print('OperationalError updating cases')
                    time.sleep(.1)
                    Case.objects.filter(id__in=case_ids).update(updated_time=datetime.datetime.utcnow().replace(tzinfo=utc))
                    case_ids = None
     
    return last_entries_saved, total_entries_duplicate, total_cases, total_entries


class Command(BaseCommand):
    args = 'No args.'
    help = 'Download court feeds and store docket data.'

    def handle(self, *args, **options):
        #THE BELOW IS FOR DEBUGGING DELETE LATER 1/2
        #Delete all cases/entries from after a certain time
        # delete_check = input('Delete cases? Enter "yes"')
        # if delete_check == 'yes':
        #Case.objects.filter(captured_time__gte=datetime.datetime(2011, 1, 1, 4, 6, 4, 335000, tzinfo=utc)).delete()
        #Entry.objects.filter(captured_time__gte=datetime.datetime(2011, 1, 1, 4, 6, 4, 335000, tzinfo=utc)).delete()
        #Court.objects.all().update(last_updated=datetime.datetime(2011, 1, 1, 4, 6, 4, 335000, tzinfo=utc))
        #print('Cases deleted.')
        
        #sudo -i -u postgres psql -d newstools -c 'TRUNCATE pacertracker_case CASCADE;'
        #END DEBUGGING SECTION
        
        #Used to calculate run time and start time
        time_started = datetime.datetime.utcnow().replace(tzinfo=utc)
        download_start = timeit.default_timer()
        
        #Count total cases, entries and skips
        total_cases = 0
        total_entries = 0
        total_entries_duplicate = 0
        total_entries_old = 0
        total_entries_broken = 0
        courts_broken = 0
        courts_old = 0
        
        #Get courts list
        courts = Court.objects.filter(has_feed=True).order_by('id')
        #THIS IS FOR DEBUGGING CUT LATER 2/2
        #downloaded_courts = courts
        
        # #Get or create the path for storing the feeds
        feeds_path = pacertracker.__path__[0].replace('\\','/') + '/feeds'
        if not os.path.exists(feeds_path):
            os.makedirs(feeds_path)

        #For saving the courts that don't fail when downloading
        downloaded_courts = []
        
        #Download the court feeds
        with futures.ThreadPoolExecutor(max_workers=30) as executor:
            feed_download = dict((executor.submit(download_feed, court, feeds_path), court)
                        for court in courts)
            
            for future in futures.as_completed(feed_download):
                court = feed_download[future]
                if future.exception() is not None:
                    self.stdout.write('%s|"error"|"could not connect to feed (timeout or partial read)"|"%s"|"%s"' % 
                                        (time_started,
                                        court.get_type_display() + ': ' + court.name,
                                        future.exception()))
                    courts_broken += 1
                else:
                    downloaded_courts.append(court)

        #Log download time
        download_time = timeit.default_timer() - download_start
        self.stdout.write('%s|"download_total"|%s|%s|%s|"%s"' % (
                            time_started, str(len(downloaded_courts)), str(courts_broken), str(courts_old),
                            download_time))
        
        #Log feed processing time and the data processing time
        feed_start = timeit.default_timer()
        feed_times = []
        data_times = []

        ##############
        #Now we load all the entries into a list for later bulk saving
        ##############
        
        #This is used to hold entries until they are de-duplicated and saved
        entries_to_save = []
        
        feed_times.append(timeit.default_timer() - feed_start)
        
        for court in downloaded_courts:
            feed_start = timeit.default_timer()

            #This is used to check if their are entries exactly the same as those in
            #entries_to_save, which is necessary because Python is apparently faster
            #than the database. We reset it for each court because no duplicates
            #between courts.
            last_entries_saved = []
            
            with open('%s/%s - %s.xml' % (feeds_path, court.name, court.get_type_display()), 'rb') as feed_open:
                feed = BeautifulSoup(feed_open, "lxml-xml")
            
            #If no feed was found, log the error
            if not feed or not feed.title or '404' in feed.title.text or '500' in feed.title.text or '503' in feed.title.text:
                self.stdout.write('%s|"error"|"No feed or entries"|"%s"' % (time_started,
                                    court.get_type_display() + ': ' + court.name))
                continue
                
            #Get the time the feed was updated
            try:
                time_updated = parser.parse(feed.lastBuildDate.text, tzinfos=get_tzinfos())
            except:
                self.stdout.write('%s|"error","Could not save feed (Error while getting court.last_updated)"|"%s"|"%s"' % (time_started,
                                    court.get_type_display() + ': ' + court.name,
                                     feed))
                courts_broken += 1
                continue

            # Checking that the last_updated time has a TZ
            try:
                compare = court.last_updated >= time_updated
            except:
                print(court.last_updated)
                print(time_updated)
                self.stdout.write('%s|"error","Could not save feed (Could not get TZ with  court.last_updated)"|"%s"|"%s"' % (time_started,
                                    court.get_type_display() + ': ' + court.name,
                                     feed))
                continue
            
            #If the feed is not new, go to next feed
            if court.last_updated >= time_updated:
                courts_old += 1
                continue
            
            #Also get the time the feed was scraped for logging
            time_scraped = datetime.datetime.utcnow().replace(tzinfo=utc)
            
            feed_times.append(timeit.default_timer() - feed_start)

            for entry in feed.findAll('item'):
                feed_start = timeit.default_timer()

                #Get time entry was filed
                try:
                    time_filed = parser.parse(entry.pubDate.text, tzinfos=get_tzinfos())
                except (KeyError, TypeError, AttributeError):
                    self.stdout.write('%s|"error"|"Could not save entry (invalid pub date)"|"%s"|"%s"' % 
                                        (time_started,
                                        court.get_type_display() + ': ' + court.name,
                                        entry))
                    total_entries_broken += 1
                    continue

                #If the entry is not new, go to next entry
                if court.last_updated >= time_filed:
                    total_entries_old += 1
                    continue

                #Get case information first
                #Title, number, name, type, website, case id
                try:
                    title, case_website = entry.title.text.strip(), entry.link.text.strip()
                    # case ids are a concatenation of the court's id, the number 0, and the number in the case website
                    # all turned into an integer to save space in the database
                    case_id = int(str(court.id) + '0' + re.search('[0-9]+(?=(&|$))', case_website.replace('-','')).group())
                    case_number, name = title.partition(' ')[0], title.partition(' ')[2].strip()
                except (KeyError,AttributeError):
                    self.stdout.write('%s|"error"|"Could not get case title, website or id."|"%s"|"%s"' % 
                                        (time_started,
                                        court.get_type_display() + ': ' + court.name,
                                        entry))
                    total_entries_broken += 1
                    continue

                #Get case type
                try:
                    type = get_case_type(case_number, court)
                except AttributeError:
                    self.stdout.write('%s|"error"|"Could not get case type for entry (invalid case number?)"|"%s"|"%s"' % 
                                        (time_started,
                                        court.get_type_display() + ': ' + court.name,
                                        entry))
                    total_entries_broken += 1
                    continue

                #Then, get the rest of the document/docket entry
                #information: description, doc number, doc website.
                try:
                    description, doc_number, doc_website = get_entry_info(entry)
                except (AttributeError, KeyError):
                    self.stdout.write('%s|"error"|"Could not get case description, doc number or doc url."|"%s"|"%s"' % 
                                        (time_started,
                                        court.get_type_display() + ': ' + court.name,
                                        entry))
                    total_entries_broken += 1
                    continue
                
                #Set is_date_filed
                if doc_number == 1:
                    is_date_filed = True
                else:
                    is_date_filed = False

                #Getting ready to check for cases/entries and for saving the cases/entries
                entry_id = case_website + description + str(doc_number) + str(doc_website) + str(time_filed)
                entry_id = uuid.UUID(hashlib.md5(entry_id.encode('utf-8')).hexdigest())
                entries_to_save.append((court, title, case_number, name, type, is_date_filed, 
                                        case_website, description, doc_number, doc_website, time_filed, 
                                        entry_id, case_id))
                
                feed_times.append(timeit.default_timer() - feed_start)
                
                #If entries reaches a certain size, save the entries and start over
                #You can tweak the number of entries to see if it will run faster on your
                #server
                data_start = timeit.default_timer()
                if len(entries_to_save) == 500:
                    (last_entries_saved, 
                     total_entries_duplicate, 
                     total_cases, 
                     total_entries) = save_everything(last_entries_saved, entries_to_save, 
                                                      total_entries_duplicate, total_cases, total_entries)
                    entries_to_save = []
                data_times.append(timeit.default_timer() - data_start)
                                        
            #Save the remaining entries for this court
            #You have to save entries at the end of each court or it will enter duplicate entries
            data_start = timeit.default_timer()
            (last_entries_saved, 
             total_entries_duplicate, 
             total_cases, 
             total_entries) = save_everything(last_entries_saved, entries_to_save, 
                                              total_entries_duplicate, total_cases, total_entries)
            entries_to_save = []
            data_times.append(timeit.default_timer() - data_start)

            #Update the court's last updated time
            feed_start = timeit.default_timer()
            court.last_updated = time_updated
            court.save(update_fields=['last_updated'])
            feed_times.append(timeit.default_timer() - feed_start)
            
            
        ##########
        #Add everything to the Solr index!
        #########
        index_start = timeit.default_timer()
        call_command('update_index', start_date=time_started.isoformat(), verbosity=0)
        #The above update_index command will not work with the next version of Haystack (2.1.0)
        #You should be able to use this one when that version is released...
        #http://stackoverflow.com/questions/4358771/
        #call_command('update_index', start_date=time_started.isoformat(), handle=['default'])
        index_time = timeit.default_timer() - index_start

        ###########
        #Finish up with some logging
        ###########
        feed_elapsed = str(sum([x for x in feed_times]))
        self.stdout.write('%s|"feed_total"|"%s"' % (
                            time_started, feed_elapsed))
        
        data_elapsed = str(sum([x for x in data_times]))
        self.stdout.write('%s|"data_total"|%s|%s|%s|%s|%s|%s|%s|%s|"%s"' % (
                            time_started, str(0), str(total_cases), str(total_entries), 
                            str(courts_broken), str(courts_old),
                            str(total_entries_old), str(total_entries_duplicate), str(total_entries_broken),
                            data_elapsed))

        self.stdout.write('%s|"index_total"|"%s"' % (
                            time_started, index_time))
        
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        self.stdout.write('%s|"time_total"|%s|%s|%s|%s|%s|%s|%s|"%s"' % (
                            time_ended, str(total_cases), str(total_entries), 
                            str(courts_broken), str(courts_old),
                            str(total_entries_old), str(total_entries_duplicate), str(total_entries_broken),
                            time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))
