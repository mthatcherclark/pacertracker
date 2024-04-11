import os
import datetime
import timeit
import time
import re
import requests
import html
import uuid
import hashlib
import logging

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
logger = logging.getLogger(__name__)

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
    
    Case numbers contain a short code meant to specify a case type.
    Often this is after a two digit year and then a dash.
    It is then followed by another dash.
    
    This is most important for District Court cases, which can be 
    civil or criminal. Usually, 'cr' means criminal and 'cv' 
    means civil.
    
    However, courts do not need to use 'cr' or 'cv' and have used a
    wide and ever-changing range of case types. As far as has been
    seen, no court has yet used the same code for civil and criminal
    cases, but this may be possible (though perhaps not within a 
    single district).
    
    The below is an ongoing attempt to differentiate them based on
    these codes, as they have been collected.
    
    Unfortunately, the codes do not need to be two characters. They
    can be two numbers, three characters, one number, etc.
    
    If an entry in a feed does not have one of the codes in this function,
    a warning will be recorded but the entry will still be stored, as civil.
    """
    if court.type == 'B':
        type = '3BK'
    elif court.type == 'A' or court.type == 'S':
        type = '4AP'
    elif court.type == 'M':
        type = '5MD'
    else:
        type = re.search('(?<=-)\w{1,4}(?=-)', case_number).group()
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
            or type == 'op' or type == 'ph' or type == 'BC' or type == 'sb' or type == 'rf'
            or type == 'pq' or type == 'mn' or type == 'gs' or type == 'LB' or type == 'tw'
            or type == 'ms' or type == 'so' or type == 'mi' or type == 'sc' or type == 'wi'
            or type == 'rc' or type == 'la' or type == 'da' or type == 'sf' or type == 'dm'):
            type = '1CV'
        elif (type == 'cr' or type == 'mj' or type == 'po' or type == 'gj' or type == 'cb'
                or type == 'tp' or type == 'pt' or type == 'fj' or type == 'tk'
                or type == 'hc' or type == 'cn' or type == 'xr' or type == 'pr'
                or type == 'mw' or type == 'r' or type == 'sm' or type == 'm'
                or type == 'te' or type == 'mr' or type == 'mb'
                or type == 'mm' or type == '~gr' or type == 'y' or type == 'mj' 
                or type == 'wt' or type == 'tr'):
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
            # THIS DOES NOT UPDATE CASE TYPE, WHICH MAY CHANGE IF CASE TYPE WAS UNKNOWN AND NOT CIVIL
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
                    error_msg = 'WARNING - %s - Trackcases experienced IntegrityError when saving cases, trying again.'
                    error_msg = (error_msg % (datetime.datetime.utcnow().replace(tzinfo=utc)
                                 ))
                    logger.warning(error_msg)
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
                    error_msg = 'WARNING - %s - Trackcases experienced OperationalError when setting updated time of cases, trying again.'
                    error_msg = (error_msg % (datetime.datetime.utcnow().replace(tzinfo=utc)
                                 ))
                    logger.warning(error_msg)
                    time.sleep(.1)
                    Case.objects.filter(id__in=case_ids).update(updated_time=datetime.datetime.utcnow().replace(tzinfo=utc))
                    case_ids = None
     
    return last_entries_saved, total_entries_duplicate, total_cases, total_entries


class Command(BaseCommand):
    args = 'No args.'
    help = 'Download court feeds and store docket data.'

    def handle(self, *args, **options):
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
        
        #Get or create the path for storing the feeds
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
                    error_msg = 'ERROR - %s - Trackcases could not connect to feed (timeout or partial read). - %s - %s'
                    error_msg = (error_msg % (time_started,
                                 court.get_type_display() + ': ' + court.name,
                                 future.exception()))
                    logger.error(error_msg)
                    courts_broken += 1
                else:
                    downloaded_courts.append(court)

        #Log download time
        download_time = timeit.default_timer() - download_start
        info_msg = 'INFO - %s - Trackcases downloaded %s courts in %s seconds, %s were broken and %s were stale.'
        info_msg = (info_msg % (time_started,
                    str(len(downloaded_courts)),
                    download_time,
                    str(courts_broken),
                    str(courts_old)
                    ))
        logger.info(info_msg)
        
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
                error_msg = 'ERROR - %s - Trackcases found no feed or an empty feed. - %s'
                error_msg = (error_msg % (time_started,
                             court.get_type_display() + ': ' + court.name
                             ))
                logger.error(error_msg)
                courts_broken += 1

                continue
                
            #Get the time the feed was updated
            try:
                time_updated = parser.parse(feed.lastBuildDate.text, tzinfos=get_tzinfos())
            except:
                error_msg = 'ERROR - %s - Trackcases feed not saved because no last_updated found. - %s'
                error_msg = (error_msg % (time_started,
                             court.get_type_display() + ': ' + court.name
                             ))
                logger.error(error_msg)

                courts_broken += 1
                continue

            # Checking that the last_updated time has a TZ
            try:
                compare = court.last_updated >= time_updated
            except:
                error_msg = 'ERROR - %s - Trackcases feed not saved because TZ is missing from last_updated. - %s - %s'
                error_msg = (error_msg % (time_started,
                             court.get_type_display() + ': ' + court.name,
                             feed
                             ))
                logger.error(error_msg)

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
                    error_msg = 'ERROR - %s - Trackcases entry not saved due to invalid pub date. - %s - %s'
                    error_msg = (error_msg % (time_started,
                                 court.get_type_display() + ': ' + court.name,
                                 entry
                                 ))
                    logger.error(error_msg)

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
                    error_msg = 'ERROR - %s - Trackcases entry not saved due to problem with title, website or id. - %s - %s'
                    error_msg = (error_msg % (time_started,
                                 court.get_type_display() + ': ' + court.name,
                                 entry
                                 ))
                    logger.error(error_msg)

                    total_entries_broken += 1
                    continue
                    
                #Get case type
                try:
                    type = get_case_type(case_number, court)
                except AttributeError:
                    error_msg = 'WARNING - %s - Trackcases entry had unknown case type or bad case number, but was saved as a civil case type entry. - %s - %s'
                    error_msg = (error_msg % (time_started,
                                 court.get_type_display() + ': ' + court.name,
                                 entry
                                 ))
                    logger.warning(error_msg)
                    
                    type = '1CV'
                    
                    total_entries_broken += 1

                #Then, get the rest of the document/docket entry
                #information: description, doc number, doc website.
                try:
                    description, doc_number, doc_website = get_entry_info(entry)
                except (AttributeError, KeyError):
                    error_msg = 'ERROR - %s - Trackcases entry not saved due to problem with description, doc number or doc url. - %s - %s'
                    error_msg = (error_msg % (time_started,
                                 court.get_type_display() + ': ' + court.name,
                                 entry
                                 ))
                    logger.error(error_msg)

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
        # Add everything to the Solr index!
        #########
        index_start = timeit.default_timer()
        call_command('update_index', start_date=time_started.isoformat(), verbosity=0)
        index_time = timeit.default_timer() - index_start

        ###########
        #Finish up with some logging
        ###########
        feed_elapsed = str(sum([x for x in feed_times]))
        info_msg = 'INFO - %s - Trackcases processed feeds in %s.'
        info_msg = (info_msg % (time_started,
                    feed_elapsed
                    ))
        logger.info(info_msg)
        
        data_elapsed = str(sum([x for x in data_times]))
        
        info_msg = 'INFO - %s - Trackcases saved %s entries from %s cases to database in %s seconds.'
        info_msg = (info_msg % (time_started,
                    str(total_entries),
                    str(total_cases),
                    data_elapsed
                    ))
        logger.info(info_msg)

        info_msg = 'INFO - %s - Trackcases indexed entries in %s seconds.'
        info_msg = (info_msg % (time_started,
                    index_time
                    ))
        logger.info(info_msg)
        
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        logger.info('INFO - %s - Trackcases finished after %s' % ( 
                    time_ended, 
                    time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))
        logger.info('INFO - %s - Trackcases saved %s cases and %s entries.' % (
                    time_ended, 
                    str(total_cases), 
                    str(total_entries)))
        logger.info('INFO - %s - Trackcases found %s broken courts and %s stale courts.' % (
                    time_ended, 
                    str(courts_broken), 
                    str(courts_old)))
        logger.info('INFO - %s - Trackcases found %s old entries, %s duplicate entries and %s broken entries.' % (
                    time_ended, 
                    str(total_entries_old), 
                    str(total_entries_duplicate), 
                    str(total_entries_broken)))

