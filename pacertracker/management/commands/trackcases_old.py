import os
import feedparser
import datetime
import timeit
import time
import re, string
from time import mktime
import requests
from concurrent import futures
import operator
from operator import __or__ as OR
from functools import reduce

from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.core.exceptions import MultipleObjectsReturned
from django.db.utils import IntegrityError, OperationalError
from django.utils.timezone import utc
from django.db.models import Q
from django import db

import pacertracker
from pacertracker.models import Court, Case, Entry
from pacertracker.search_indexes import CaseIndex



def download_feed(court, feeds_path):
    """
    Downloads court feeds
    """
    response = requests.get(court.feed_url, timeout=20)

    with open('%s/%s - %s.xml' % (feeds_path, court.name, court.get_type_display()), 'w') as out:
        out.write(response.text)
    
    return None


def get_case_type(case_number, court):
    """
    Gets the case type and returns it
    """
    #xr is criminal and civil? Typo?
    #s1 is invalid, a bad entry (contained a dash between case number and name, no space

    if court.type == 'B':
        type = '3BK'
    elif court.type == 'A' or court.type == 'S':
        type = '4AP'
    elif court.type == 'M':
        type = '5MD'
    else:
        type = re.search('(?<=-)\w{2}(?=-)', case_number).group()
        #District Court cases with a "bk" as case type are multidistrict (civil) not bankruptcy
        if (type == 'cv' or type == 'mc' or type == 'ct' or type == 'dp' or type == 'md'
            or type == 'cm' or type == 'fp' or type == 'gd' or type == 'ml' or type == 'pf'
            or type == 'sw' or type == 'xc' or type == 'af' or type == 'de' or type == 'dj'
            or type == 'gp' or type == 'oe' or type == 'aa' or type == 'at' or type == 'adr'
            or type == 's1' or type == 'av' or type == 'wp' or type == 'adr' or type == '2255'
            or type == 'wf' or type == 's' or type == 'dcn' or type == 'ad' or type == 'w'
            or type == 'ds' or type == 'sp' or type == 'rd' or type == 'rj' or type == 'bk'):
            type = '1CV'
        elif (type == 'cr' or type == 'mj' or type == 'po' or type == 'gj' or type == 'cb'
                or type == 'tp' or type == 'pt' or type == 'fj' or type == 'tk'
                or type == 'hc' or type == 'cn' or type == 'xr' or type == 'pr'
				or type == 'mw' or type == 'r' or type == 'sm' or type == 'm'
                or type == 'te' or type == 'mr' or type == 'mb'):
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
    
    #Some bankruptcy cases have more than just a docket name. Capture that, too.
    if 'Trustee: ' in entry['summary']:
        description = re.search('Trustee: .+(?=\])', entry['summary']).group() + ']'
    else:
        description = re.search('(?<=\[).+(?=\])', entry['summary']).group()
    
    number = re.search('(?<=">)\d+(?=</a>)', entry['summary'])
    website = re.search('(?<=a href=").+(?=">)', entry['summary'])

    if number and website:
        return description, int(number.group()), website.group()
    elif website:
        return description, None, website.group()
    else:
        return description, None, ''


def save_everything(last_entries_saved, entries_to_save, total_entries_duplicate, total_cases, total_entries):
    #############
    # Save the cases and entries
    #############
    
    #First, remove duplicates from the list
    old_length = len(entries_to_save)
    #Note: this assumes the duplicate entries within the feeds do not contain different case titles and such
    #May have to re-work this later, continue for now
    entries_to_save = list(set(entries_to_save))
    #Because Python is faster than the database???, we have to check for duplicates using last_entries_saved
    entries_to_save = [x for x in entries_to_save if x not in last_entries_saved]
    total_entries_duplicate += old_length - len(entries_to_save)

    if entries_to_save:
        #Find the entries that already exist
        qlist = []
        for qitem in entries_to_save:
            qlist.append(Q(case__website=qitem[6]) &
                        Q(description=qitem[7]) &
                        Q(number=qitem[8]) &
                        Q(website=qitem[9]) &
                        Q(time_filed=qitem[10]))
        #Get any entry with a similar field value
        returned_entries = list(Entry.objects.filter(reduce(OR, 
                                qlist)).select_related('case').values_list(
                                'case__website', 'description', 'number', 
                                'website', 'time_filed'))

        #Eliminate any entry with identical field values
        indices_to_delete = [i for i, x in enumerate(entries_to_save) if x[6:10] in returned_entries]
        entries_to_save = [x for i, x in enumerate(entries_to_save) if i not in indices_to_delete]
        total_entries_duplicate += len(indices_to_delete)
        for x in entries_to_save:
            last_entries_saved.append(x)

        if entries_to_save:
            #Obtain unique list of cases
            websites = [x[6] for x in entries_to_save]
            cases_to_save = [x for i, x in enumerate(entries_to_save) if x[6] not in websites[i + 1:]]
            
            #Update the titles, names and numbers of cases if they are different
            returned_case_dict = dict([(c.website, c) for c in Case.objects.filter(website__in=websites)])
            
            for case_to_update in cases_to_save:
                if case_to_update[6] in returned_case_dict:
                    case = returned_case_dict[case_to_update[6]]
                    if case.title != case_to_update[1]:
                        case.title = case_to_update[1]
                        case.number, case_name = case_to_update[2], case_to_update[3]
                        case.save(update_fields=['title', 'name', 'number'])

            #Save the new cases
            #Find cases the cases that have already been entered=
            try:
                returned_cases = list(Case.objects.filter(website__in=websites).values_list('website', flat=True))
                cases_to_save = [Case(court=x[0], title=x[1], website=x[6], number=x[2], name=x[3], type=x[4], 
                                 is_date_filed=x[5], case_key=x[11]) for x in cases_to_save if x[6] not in returned_cases]
                Case.objects.bulk_create(cases_to_save)
            except IntegrityError:
                time.sleep(5)
                returned_cases = list(Case.objects.filter(website__in=websites).values_list('website', flat=True))
                cases_to_save = [Case(court=x[0], title=x[1], website=x[6], number=x[2], name=x[3], type=x[4], 
                                 is_date_filed=x[5], case_key=x[11]) for x in cases_to_save if x[6] not in returned_cases]
                Case.objects.bulk_create(cases_to_save)

            total_cases += len(cases_to_save)

            #Get the cases for each entry, including those we just saved
            returned_cases = list(Case.objects.filter(website__in=websites))
            websites = [x.website for x in returned_cases]

            #Save the entries
            for indice, new_entry in enumerate(entries_to_save):
                case = returned_cases[websites.index(new_entry[6])]
                entries_to_save[indice] = Entry(case=case, description=new_entry[7], number=new_entry[8], 
                                                website=new_entry[9], time_filed=new_entry[10])

            Entry.objects.bulk_create(entries_to_save)
            total_entries += len(entries_to_save)
            try:
                Case.objects.filter(website__in=websites).update(updated_time=datetime.datetime.utcnow().replace(tzinfo=utc))
            except OperationalError:
                time.sleep(5)
                Case.objects.filter(website__in=websites).update(updated_time=datetime.datetime.utcnow().replace(tzinfo=utc))
            
     
    return last_entries_saved, total_entries_duplicate, total_cases, total_entries


class Command(BaseCommand):
    args = 'No args.'
    help = 'Download court feeds and store docket data.'

    def handle(self, *args, **options):
        #THE BELOW IS FOR DEBUGGING DELETE LATER
        #import logging
        #l = logging.getLogger('django.db.backends')
        #l.setLevel(logging.DEBUG)
        #l.addHandler(logging.StreamHandler())
        #Delete all cases/entries from after a certain time
        # delete_check = input('Delete cases? Enter "yes"')
        # if delete_check == 'yes':
        Case.objects.filter(captured_time__gte=datetime.datetime(2011, 1, 1, 4, 6, 4, 335000, tzinfo=utc)).delete()
        Entry.objects.filter(captured_time__gte=datetime.datetime(2011, 1, 1, 4, 6, 4, 335000, tzinfo=utc)).delete()
        Court.objects.all().update(last_updated=datetime.datetime(2011, 1, 1, 4, 6, 4, 335000, tzinfo=utc))
        #db.reset_queries()
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
        #THIS IS FOR DEBUGGING CUT LATER
        downloaded_courts = courts
        
        #Get or create the path for storing the feeds
        feeds_path = pacertracker.__path__[0].replace('\\','/') + '/feeds'
        if not os.path.exists(feeds_path):
            os.makedirs(feeds_path)

        # #For saving the courts that don't fail when downloading
        # downloaded_courts = []
        
        # #Download the court feeds
        # with futures.ThreadPoolExecutor(max_workers=15) as executor:
            # feed_download = dict((executor.submit(download_feed, court, feeds_path), court)
                        # for court in courts)
            
            # for future in futures.as_completed(feed_download):
                # court = feed_download[future]
                # if future.exception() is not None:
                    # self.stdout.write('%s|"error"|"could not connect to feed (timeout or partial read)"|"%s"|"%s"' % 
                                        # (time_started,
                                        # court.get_type_display() + ': ' + court.name,
                                        # future.exception()))
                    # courts_broken += 1
                # else:
                    # downloaded_courts.append(court)

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
                feed_file = feed_open.read()
                feed = feedparser.parse(feed_file)
            
            #If no feed was found, log the error
            if not feed['feed']:
                self.stdout.write('%s|"error"|"No feed found"|"%s"' % (time_started,
                                    court.get_type_display() + ': ' + court.name))
                continue
            
            #Skip fees without entries...
            if not feed['entries']:
                continue
                
            #Get the time the feed was updated
            try:
                time_updated = datetime.datetime.fromtimestamp(mktime(feed['entries'][0]['updated_parsed'])).replace(tzinfo=utc)
            except (KeyError):
                self.stdout.write('%s|"error","Could not save feed (KeyError while getting court.last_updated)"|"%s"|"%s"' % (time_started,
                                    court.get_type_display() + ': ' + court.name,
                                     feed['feed']))
                courts_broken += 1
                continue
            except (TypeError):
                self.stdout.write('%s|"error","Could not save feed (TypeError while getting court.last_updated)"|"%s"|"%s"' % (time_started,
                                    court.get_type_display() + ': ' + court.name,
                                     feed['feed']))
                courts_broken += 1
                continue

            #If the feed is not new, go to next feed
            if court.last_updated >= time_updated:
                courts_old += 1
                continue
            
            #Also get the time the feed was scraped for logging
            time_scraped = datetime.datetime.utcnow().replace(tzinfo=utc)
            
            feed_times.append(timeit.default_timer() - feed_start)

            for entry in feed['entries']:
                feed_start = timeit.default_timer()

                #Get time entry was filed
                try:
                    time_filed = datetime.datetime.fromtimestamp(mktime(entry['updated_parsed'])).replace(tzinfo=utc)
                except (KeyError, TypeError):
                    self.stdout.write('%s|"error"|"Could not save entry (invalid updated_parsed)"|"%s"|"%s"' % 
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
                #Title, number, name, type, website
                try:
                    title, case_website = entry['title'], entry['link']
                    # case_key is a concatenation of the court's id, the number 9, and the number in the case website
                    # turned into an integer to save space in the database
                    case_key = int(str(court.id) + re.search('[0-9]+(?=(&|$))', case_website.replace('-','')).group())
                    case_number, name = title.partition(' ')[0], title.partition(' ')[2]
                except KeyError:
                    self.stdout.write('%s|"error"|"Could not get case title (and number and name) or website."|"%s"|"%s"' % 
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
                entries_to_save.append((court, title,  case_number, name, type, is_date_filed, 
                                        case_website, description, doc_number, doc_website, time_filed,
                                        case_key))
                
                feed_times.append(timeit.default_timer() - feed_start)
                
                #If entries reaches a certain size, save the entries and start over
                #You can tweak the number of entries to see if it will run faster on your
                #server
                data_start = timeit.default_timer()
                if len(entries_to_save) == 150:
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
                            time_started, str(len(db.connection.queries)), str(total_cases), str(total_entries), 
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