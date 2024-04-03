import os
import datetime
import timeit
import time
import csv
import logging
import zipfile

from dateutil import parser
from dateutil.tz import gettz
from internetarchive import upload

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings

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
        
        for entry in entries[:2000000]:
            writer.writerow(entry)
    
    return None
    

class Command(BaseCommand):
    args = 'No args.'
    help = 'Send courts, cases and YTD entries to Internet Archive and delete old entries.'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--noupload',
            action='store_true',
            dest='noupload',
            default=False,
            help='Do not upload to the Internet Archive.',
        )

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
            
            for case in cases[:2000000]:
                writer.writerow(case)
        
        # If the entries file does not exist for this year, 
        # check if it exists for the prior year.
        # If it exists for prior year, make sure the prior file 
        # has all the entries for that year by using ID and date filters.
        # Then, create the new file and add to it.
        # If there is no prior file, just create the new file for this year
        old_file = False # For keeping track of whether there is an old file to be uploaded
        if not os.path.exists(entries_filename):
            old_entries_filename = ('%s/%sentries.csv' % (feeds_path, datetime.date.today().year -1))
            old_file = True
            
            if not os.path.exists(old_entries_filename): # Old one nonexistent, create current year only
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
        
        # Used for tracking time it takes to create files, zip and then upload
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        logger.info('INFO - %s - Archive finished creating files after %s' % ( 
                    time_ended, 
                    time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))
                    
                    
        # ZIP the files for upload
        # ZIP Filename conventions
        courts_zipname = ('%s/courts.zip' % (feeds_path))
        cases_zipname = ('%s/cases.zip' % (feeds_path))
        entries_zipname = ('%s/%sentries.zip' % (feeds_path, datetime.date.today().year))
        old_entries_zipname = ('%s/%sentries.zip' % (feeds_path, datetime.date.today().year))
        
        
        with zipfile.ZipFile(courts_zipname, "w", zipfile.ZIP_DEFLATED) as zfile:
            zfile.write(courts_filename)
        
        with zipfile.ZipFile(cases_zipname, "w", zipfile.ZIP_DEFLATED) as zfile:
            zfile.write(cases_filename)        
        
        with zipfile.ZipFile(entries_zipname, "w", zipfile.ZIP_DEFLATED) as zfile:
            zfile.write(entries_filename)
       
        if old_file:
            with zipfile.ZipFile(old_entries_zipname, "w", zipfile.ZIP_DEFLATED) as zfile:
                zfile.write(old_entries_filename)
            
        # Used for tracking time it takes to create files, zip and then upload
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        logger.info('INFO - %s - Archive finished zipping files after %s' % ( 
                    time_ended, 
                    time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))
        
        # Now, we upload to Internet Archive
        if old_file and not options['noupload']:
            r = upload(settings.IA_IDENTIFIER, 
                       files=[courts_filename,cases_filename,entries_filename,old_entries_filename], 
                       access_key=settings.IA_ACCESS_KEY, 
                       secret_key=settings.IA_SECRET_KEY)
            r[0].status_code
        elif not options['noupload']:
            r = upload(settings.IA_IDENTIFIER, 
                       files=[courts_filename,cases_filename,entries_filename], 
                       access_key=settings.IA_ACCESS_KEY, 
                       secret_key=settings.IA_SECRET_KEY)
            r[0].status_code

        # Log stuff
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        logger.info('INFO - %s - Archive finished uploading after %s' % ( 
                    time_ended, 
                    time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))

