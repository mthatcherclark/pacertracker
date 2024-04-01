import os
import datetime
import timeit
import time
import csv
import logging

from dateutil import parser
from dateutil.tz import gettz

from django.core.management.base import BaseCommand
from django.core.management import call_command

import pacertracker
from pacertracker.models import Court, Case, Entry

utc = datetime.timezone.utc
logger = logging.getLogger(__name__)

court_fields = ['id','name','type','has_feed','publishes_all','filing_types','feed_url','website','last_updated']
cases_fields = ['id','number','name','type','website','captured_time','is_date_filed','court_id']
entries_fields = ['id','time_filed','captured_time','description','number','website','case_id']

def get_last_line(file, how_many_last_lines = 1):
    # open your file using with: safety first, kids!
    with open(file, 'r') as file:

        # find the position of the end of the file: end of the file stream
        end_of_file = file.seek(0,2)
        
        # set your stream at the end: seek the final position of the file
        file.seek(end_of_file)             
        
        # trace back each character of your file in a loop
        n = 0
        for num in range(end_of_file+1):            
            file.seek(end_of_file - num)    
           
            # save the last characters of your file as a string: last_line
            last_line = file.read()
           
            # count how many '\n' you have in your string: 
            # if you have 1, you are in the last line; if you have 2, you have the two last lines
            if last_line.count('\n') == how_many_last_lines +1: 
                return last_line[2:]
                
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

def update_entries_file(filename, io_type, fields, filter_from, filter_to=None):
    with open(filename, io_type, newline='') as csvfile:
        writer = csv.writer(csvfile)
        
        if io_type == 'w':
            writer.writerow(fields)
        
        if filter_to: # Used for last update of prior year
            entries = Entry.objects.filter(captured_time__gt=filter_from,
                                           captured_time__year=filter_to
                                           ).order_by('captured_time'
                                           ).values_list(*fields)
        elif io_type == 'w': # New files contain all entries for current year
            entries = Entry.objects.filter(captured_time__year=filter_from
                                           ).order_by('captured_time'
                                           ).values_list(*fields)
        else:
            entries = Entry.objects.filter(captured_time__gt=filter_from
                                           ).order_by('captured_time'
                                           ).values_list(*fields)
        
        for entry in entries:
            writer.writerow(entry)
    
    return None
    

class Command(BaseCommand):
    args = 'No args.'
    help = 'Send courts, cases and YTD entries to Internet Archive and delete old entries.'

    def handle(self, *args, **options):
        #Used to calculate run time and start time
        time_started = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        # Get or create the path for storing the CSVs
        feeds_path = pacertracker.__path__[0].replace('\\','/') + '/archives'
        if not os.path.exists(feeds_path):
            os.makedirs(feeds_path)

        # Filename conventions
        courts_filename = ('%s/courts.csv' % (feeds_path))
        cases_filename = ('%s/cases.csv' % (feeds_path))
        entries_filename = ('%s/%sentries.csv' % (feeds_path, datetime.date.today().year))
        
        # Create courts file every time
        with open(courts_filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(court_fields)
            
            courts = Court.objects.all().values_list(*court_fields)
            
            for court in courts:
                writer.writerow(court)


        # Create cases file every time
        with open(cases_filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(cases_fields)
            
            cases = Case.objects.all().values_list(*cases_fields)
            
            for case in cases:
                writer.writerow(case)
        
        # If the entries file does not exist for this year, 
        # check if it exists for the prior year.
        # If it exists for prior year, make sure the prior file 
        # has all the entries for that year by using ID and date filters.
        # Then, create the new file and add to it.
        # If there is no prior file, just create the new file for this year
        if not os.path.exists(entries_filename):
            old_entries_filename = ('%s/%sentries.csv' % (feeds_path, datetime.date.today().year -1))
            if not os.path.exists(old_entries_filename): # Old one nonexistent, create for this year
                update_entries_file(entries_filename, 
                                    'w', 
                                    entries_fields, 
                                    datetime.date.today().year)
            else:
                # If old file exists, first add remaining entries for prior year
                last_time = get_last_line(old_entries_filename, 1).split(',')[2]
                last_time = parser.parse(last_time, tzinfos=get_tzinfos())
                
                update_entries_file(old_entries_filename, 
                                    'a', 
                                    entries_fields, 
                                    filter_from=last_time, 
                                    filter_to=datetime.date.today().year - 1)
                
                # Then, create the file for the new (current) year
                update_entries_file(entries_filename, 
                                    'w', 
                                    entries_fields, 
                                    datetime.date.today().year)
        
        else: # If file exists, append most recent entries to it...
            # First, get the last ID in the CSV...
            last_time = get_last_line(entries_filename, 1).split(',')[2]
            last_time = parser.parse(last_time, tzinfos=get_tzinfos())
            
            update_entries_file(entries_filename, 
                                'a', 
                                entries_fields, 
                                filter_from=last_time)
        
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        print(time_ended)
        print(time_elapsed)
        

        
        # download_start = timeit.default_timer()
        
        # #Count total cases, entries and skips
        # total_cases = 0
        # total_entries = 0
        # total_entries_duplicate = 0
        # total_entries_old = 0
        # total_entries_broken = 0
        # courts_broken = 0
        # courts_old = 0
        
        # #Get courts list
        # courts = Court.objects.filter(has_feed=True).order_by('id')
        
        # #Get or create the path for storing the feeds
        # feeds_path = pacertracker.__path__[0].replace('\\','/') + '/feeds'
        # if not os.path.exists(feeds_path):
            # os.makedirs(feeds_path)

        # #For saving the courts that don't fail when downloading
        # downloaded_courts = []
        
        # #Download the court feeds
        # with futures.ThreadPoolExecutor(max_workers=30) as executor:
            # feed_download = dict((executor.submit(download_feed, court, feeds_path), court)
                        # for court in courts)
            
            # for future in futures.as_completed(feed_download):
                # court = feed_download[future]
                # if future.exception() is not None:
                    # error_msg = 'ERROR - %s - Trackcases could not connect to feed (timeout or partial read). - %s - %s'
                    # error_msg = (error_msg % (time_started,
                                 # court.get_type_display() + ': ' + court.name,
                                 # future.exception()))
                    # logger.error(error_msg)
                    # courts_broken += 1
                # else:
                    # downloaded_courts.append(court)

        # #Log download time
        # download_time = timeit.default_timer() - download_start
        # info_msg = 'INFO - %s - Trackcases downloaded %s courts in %s seconds, %s were broken and %s were stale.'
        # info_msg = (info_msg % (time_started,
                    # str(len(downloaded_courts)),
                    # download_time,
                    # str(courts_broken),
                    # str(courts_old)
                    # ))
        # logger.info(info_msg)
        
        # #Log feed processing time and the data processing time
        # feed_start = timeit.default_timer()
        # feed_times = []
        # data_times = []

        # ##############
        # #Now we load all the entries into a list for later bulk saving
        # ##############
        
        # #This is used to hold entries until they are de-duplicated and saved
        # entries_to_save = []
        
        # feed_times.append(timeit.default_timer() - feed_start)
        
        # for court in downloaded_courts:
            # feed_start = timeit.default_timer()

            # #This is used to check if their are entries exactly the same as those in
            # #entries_to_save, which is necessary because Python is apparently faster
            # #than the database. We reset it for each court because no duplicates
            # #between courts.
            # last_entries_saved = []
            
            # with open('%s/%s - %s.xml' % (feeds_path, court.name, court.get_type_display()), 'rb') as feed_open:
                # feed = BeautifulSoup(feed_open, "lxml-xml")
            
            # #If no feed was found, log the error
            # if not feed or not feed.title or '404' in feed.title.text or '500' in feed.title.text or '503' in feed.title.text:
                # error_msg = 'ERROR - %s - Trackcases found no feed or an empty feed. - %s'
                # error_msg = (error_msg % (time_started,
                             # court.get_type_display() + ': ' + court.name
                             # ))
                # logger.error(error_msg)
                # courts_broken += 1

                # continue
                
            # #Get the time the feed was updated
            # try:
                # time_updated = parser.parse(feed.lastBuildDate.text, tzinfos=get_tzinfos())
            # except:
                # error_msg = 'ERROR - %s - Trackcases feed not saved because no last_updated found. - %s'
                # error_msg = (error_msg % (time_started,
                             # court.get_type_display() + ': ' + court.name
                             # ))
                # logger.error(error_msg)

                # courts_broken += 1
                # continue

            # # Checking that the last_updated time has a TZ
            # try:
                # compare = court.last_updated >= time_updated
            # except:
                # error_msg = 'ERROR - %s - Trackcases feed not saved because TZ is missing from last_updated. - %s - %s'
                # error_msg = (error_msg % (time_started,
                             # court.get_type_display() + ': ' + court.name,
                             # feed
                             # ))
                # logger.error(error_msg)

                # continue
            
            # #If the feed is not new, go to next feed
            # if court.last_updated >= time_updated:
                # courts_old += 1
                # continue
            
            # #Also get the time the feed was scraped for logging
            # time_scraped = datetime.datetime.utcnow().replace(tzinfo=utc)
            
            # feed_times.append(timeit.default_timer() - feed_start)

            # for entry in feed.findAll('item'):
                # feed_start = timeit.default_timer()

                # #Get time entry was filed
                # try:
                    # time_filed = parser.parse(entry.pubDate.text, tzinfos=get_tzinfos())
                # except (KeyError, TypeError, AttributeError):
                    # error_msg = 'ERROR - %s - Trackcases entry not saved due to invalid pub date. - %s - %s'
                    # error_msg = (error_msg % (time_started,
                                 # court.get_type_display() + ': ' + court.name,
                                 # entry
                                 # ))
                    # logger.error(error_msg)

                    # total_entries_broken += 1
                    # continue

                # #If the entry is not new, go to next entry
                # if court.last_updated >= time_filed:
                    # total_entries_old += 1
                    # continue

                # #Get case information first
                # #Title, number, name, type, website, case id
                # try:
                    # title, case_website = entry.title.text.strip(), entry.link.text.strip()
                    # # case ids are a concatenation of the court's id, the number 0, and the number in the case website
                    # # all turned into an integer to save space in the database
                    # case_id = int(str(court.id) + '0' + re.search('[0-9]+(?=(&|$))', case_website.replace('-','')).group())
                    # case_number, name = title.partition(' ')[0], title.partition(' ')[2].strip()
                # except (KeyError,AttributeError):
                    # error_msg = 'ERROR - %s - Trackcases entry not saved due to problem with title, website or id. - %s - %s'
                    # error_msg = (error_msg % (time_started,
                                 # court.get_type_display() + ': ' + court.name,
                                 # entry
                                 # ))
                    # logger.error(error_msg)

                    # total_entries_broken += 1
                    # continue
                    
                # #Get case type
                # try:
                    # type = get_case_type(case_number, court)
                # except AttributeError:
                    # error_msg = 'WARNING - %s - Trackcases entry had unknown case type or bad case number, but was saved as a civil case type entry. - %s - %s'
                    # error_msg = (error_msg % (time_started,
                                 # court.get_type_display() + ': ' + court.name,
                                 # entry
                                 # ))
                    # logger.warning(error_msg)
                    
                    # type = '1CV'
                    
                    # total_entries_broken += 1

                # #Then, get the rest of the document/docket entry
                # #information: description, doc number, doc website.
                # try:
                    # description, doc_number, doc_website = get_entry_info(entry)
                # except (AttributeError, KeyError):
                    # error_msg = 'ERROR - %s - Trackcases entry not saved due to problem with description, doc number or doc url. - %s - %s'
                    # error_msg = (error_msg % (time_started,
                                 # court.get_type_display() + ': ' + court.name,
                                 # entry
                                 # ))
                    # logger.error(error_msg)

                    # total_entries_broken += 1
                    # continue
                
                # #Set is_date_filed
                # if doc_number == 1:
                    # is_date_filed = True
                # else:
                    # is_date_filed = False

                # #Getting ready to check for cases/entries and for saving the cases/entries
                # entry_id = case_website + description + str(doc_number) + str(doc_website) + str(time_filed)
                # entry_id = uuid.UUID(hashlib.md5(entry_id.encode('utf-8')).hexdigest())
                # entries_to_save.append((court, title, case_number, name, type, is_date_filed, 
                                        # case_website, description, doc_number, doc_website, time_filed, 
                                        # entry_id, case_id))
                
                # feed_times.append(timeit.default_timer() - feed_start)
                
                # #If entries reaches a certain size, save the entries and start over
                # #You can tweak the number of entries to see if it will run faster on your
                # #server
                # data_start = timeit.default_timer()
                # if len(entries_to_save) == 500:
                    # (last_entries_saved, 
                     # total_entries_duplicate, 
                     # total_cases, 
                     # total_entries) = save_everything(last_entries_saved, entries_to_save, 
                                                      # total_entries_duplicate, total_cases, total_entries)
                    # entries_to_save = []
                # data_times.append(timeit.default_timer() - data_start)
                                        
            # #Save the remaining entries for this court
            # #You have to save entries at the end of each court or it will enter duplicate entries
            # data_start = timeit.default_timer()
            # (last_entries_saved, 
             # total_entries_duplicate, 
             # total_cases, 
             # total_entries) = save_everything(last_entries_saved, entries_to_save, 
                                              # total_entries_duplicate, total_cases, total_entries)
            # entries_to_save = []
            # data_times.append(timeit.default_timer() - data_start)

            # #Update the court's last updated time
            # feed_start = timeit.default_timer()
            # court.last_updated = time_updated
            # court.save(update_fields=['last_updated'])
            # feed_times.append(timeit.default_timer() - feed_start)
            
            
        # ##########
        # #Add everything to the Solr index!
        # #########
        # index_start = timeit.default_timer()
        # call_command('update_index', start_date=time_started.isoformat(), verbosity=0)
        # index_time = timeit.default_timer() - index_start

        # ###########
        # #Finish up with some logging
        # ###########
        # feed_elapsed = str(sum([x for x in feed_times]))
        # info_msg = 'INFO - %s - Trackcases processed feeds in %s.'
        # info_msg = (info_msg % (time_started,
                    # feed_elapsed
                    # ))
        # logger.info(info_msg)
        
        # data_elapsed = str(sum([x for x in data_times]))
        
        # info_msg = 'INFO - %s - Trackcases saved %s entries from %s cases to database in %s seconds.'
        # info_msg = (info_msg % (time_started,
                    # str(total_entries),
                    # str(total_cases),
                    # data_elapsed
                    # ))
        # logger.info(info_msg)

        # info_msg = 'INFO - %s - Trackcases indexed entries in %s seconds.'
        # info_msg = (info_msg % (time_started,
                    # index_time
                    # ))
        # logger.info(info_msg)
        
        # time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        # time_elapsed = str(time_elapsed).split(':')
        # time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        # logger.info('INFO - %s - Trackcases finished after %s' % ( 
                    # time_ended, 
                    # time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))
        # logger.info('INFO - %s - Trackcases saved %s cases and %s entries.' % (
                    # time_ended, 
                    # str(total_cases), 
                    # str(total_entries)))
        # logger.info('INFO - %s - Trackcases found %s broken courts and %s stale courts.' % (
                    # time_ended, 
                    # str(courts_broken), 
                    # str(courts_old)))
        # logger.info('INFO - %s - Trackcases found %s old entries, %s duplicate entries and %s broken entries.' % (
                    # time_ended, 
                    # str(total_entries_old), 
                    # str(total_entries_duplicate), 
                    # str(total_entries_broken)))

