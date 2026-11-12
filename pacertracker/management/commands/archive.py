import os
import datetime
import timeit
import time
import csv
import logging
import zipfile

from os.path import basename

from dateutil import parser
from dateutil.relativedelta import relativedelta
from dateutil.tz import gettz
from internetarchive import upload

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings
from django.db import connection, transaction

import pacertracker
from pacertracker.models import Court, Case, Entry

utc = datetime.timezone.utc
logger = logging.getLogger(__name__)

court_fields = ['id','name','type','has_feed','publishes_all','filing_types','feed_url','website','last_updated']
cases_fields = ['id','number','name','type','website','captured_time','is_date_filed','court_id']
entries_fields = ['id','time_filed','captured_time','description','number','website','case_id']

# The database only keeps recent entries. The complete history lives in the
# annual entries files at the Internet Archive. Thirteen months is enough to
# run the site and to finish the prior year's file at the year-end rollover.
ENTRY_RETENTION_MONTHS = 13
# Deleting more rows than this one by one takes hours and leaves the table
# bloated, so above it we copy the rows we keep, truncate and re-insert them.
PRUNE_REBUILD_THRESHOLD = 1000000

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
                                           ).values_list(*fields).iterator(chunk_size=10000)
        elif io_type == 'w': # New files contain all entries for the given year
            entries = Entry.objects.filter(captured_time__year=filter_from
                                           ).order_by('captured_time'
                                           ).values_list(*fields).iterator(chunk_size=10000)
        else:
            entries = Entry.objects.filter(captured_time__gt=filter_from
                                           ).order_by('captured_time'
                                           ).values_list(*fields).iterator(chunk_size=10000)
        
        for entry in entries:
            writer.writerow(entry)
    
    return None


def get_retention_cutoff():
    now = datetime.datetime.utcnow().replace(tzinfo=utc)
    return now - relativedelta(months=ENTRY_RETENTION_MONTHS)


def prune_old_entries(cutoff):
    """Delete entries captured before cutoff and return how many went.

    A normal daily run removes about one day's worth of entries, which a
    plain DELETE handles in seconds. The first run after a long gap (or
    after restoring a full backup) has tens of millions of rows to drop,
    so it instead copies the rows to keep into a temp table, truncates the
    entries table and inserts them back, all in one transaction. TRUNCATE
    hands the space straight back to the OS; a huge DELETE would not.
    """
    table = connection.ops.quote_name(Entry._meta.db_table)
    to_delete = Entry.objects.filter(captured_time__lt=cutoff).count()

    if to_delete == 0:
        return 0

    with transaction.atomic():
        with connection.cursor() as cursor:
            if to_delete < PRUNE_REBUILD_THRESHOLD:
                cursor.execute('DELETE FROM %s WHERE captured_time < %%s' % table,
                               [cutoff])
                deleted = cursor.rowcount
            else:
                cursor.execute('CREATE TEMP TABLE entries_to_keep ON COMMIT DROP AS '
                               'SELECT * FROM %s WHERE captured_time >= %%s' % table,
                               [cutoff])
                cursor.execute('SELECT count(*) FROM entries_to_keep')
                kept = cursor.fetchone()[0]
                cursor.execute('TRUNCATE %s' % table)
                cursor.execute('INSERT INTO %s SELECT * FROM entries_to_keep' % table)
                inserted = cursor.rowcount
                if inserted != kept:
                    # Raising inside atomic() rolls everything back,
                    # including the TRUNCATE.
                    raise RuntimeError('Archive prune aborted: copied %s entries '
                                       'to keep but re-inserted %s' % (kept, inserted))
                deleted = to_delete

    # Fresh statistics for the planner after a big change
    with connection.cursor() as cursor:
        cursor.execute('ANALYZE %s' % table)

    return deleted


def zip_file(zipname, filename):
    with zipfile.ZipFile(zipname, "w", zipfile.ZIP_DEFLATED) as zfile:
        zfile.write(filename, basename(filename))
    
    return None
    

class Command(BaseCommand):
    args = 'No args.'
    help = ('Send courts, cases and YTD entries to Internet Archive, then delete '
            'entries older than %s months from the database.' % ENTRY_RETENTION_MONTHS)
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--noupload',
            action='store_true',
            dest='noupload',
            default=False,
            help='Do not upload to the Internet Archive. Old entries are not '
                 'deleted either, since nothing was archived this run.',
        )
        parser.add_argument(
            '--noprune',
            action='store_true',
            dest='noprune',
            default=False,
            help='Do not delete entries older than %s months.' % ENTRY_RETENTION_MONTHS,
        )
        parser.add_argument(
            '--pruneonly',
            action='store_true',
            dest='pruneonly',
            default=False,
            help='Only delete entries older than %s months; do not create or upload '
                 'any files. Use this for the first prune of a database that still '
                 'holds years already archived, and only once those years are '
                 'confirmed complete at the Internet Archive.' % ENTRY_RETENTION_MONTHS,
        )
        parser.add_argument(
            '--rebuild',
            action='store_true',
            dest='rebuild',
            default=False,
            help='Rebuild the entries CSV for every year still in the database, '
                 'overwriting any existing annual entries files.',
        )

    def handle(self, *args, **options):
        #Used to calculate run time and start time
        time_started = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        if options['pruneonly']:
            self.prune(time_started)
            return
        
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
            
            courts = Court.objects.all().values_list(*court_fields).iterator(chunk_size=10000)
            
            for court in courts:
                writer.writerow(court)


        # Create cases file every time
        with open(cases_filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(cases_fields)
            
            cases = Case.objects.all().values_list(*cases_fields).iterator(chunk_size=10000)
            
            for case in cases:
                writer.writerow(case)
        
        # Keeps track of every entries file we write this run so we can
        # zip and upload them all at the end.
        entries_filenames = []
        
        if options['rebuild']:
            # Rebuild one entries file per year for every year that still
            # has entries in the database. Overwrites any existing files.
            years = Entry.objects.dates('captured_time', 'year')
            cutoff = get_retention_cutoff()
            
            for year in years:
                if datetime.datetime(year.year, 1, 1, tzinfo=utc) < cutoff:
                    # Entries older than the retention window are gone, so a
                    # rebuilt file would be incomplete and would overwrite the
                    # complete one at the Internet Archive.
                    logger.warning('WARNING - Archive did not rebuild the %s entries '
                                   'file because the database no longer holds all '
                                   'of %s.' % (year.year, year.year))
                    continue
                
                year_filename = ('%s/%sentries.csv' % (feeds_path, year.year))
                
                update_entries_file(year_filename, 
                                    'w', 
                                    entries_fields, 
                                    year.year)
                
                entries_filenames.append(year_filename)
                
                logger.info('INFO - Rebuilt entries file for %s' % year.year)
        
        # If the entries file does not exist for this year, 
        # check if it exists for the prior year.
        # If it exists for prior year, make sure the prior file 
        # has all the entries for that year by using ID and date filters.
        # Then, create the new file and add to it.
        # If there is no prior file, just create the new file for this year
        elif not os.path.exists(entries_filename):
            old_entries_filename = ('%s/%sentries.csv' % (feeds_path, datetime.date.today().year - 1))
            
            if not os.path.exists(old_entries_filename): # Old one nonexistent, create current year only
                update_entries_file(entries_filename, 
                                    'w', 
                                    entries_fields, 
                                    datetime.date.today().year)
                
                entries_filenames.append(entries_filename)
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
                
                entries_filenames.append(old_entries_filename)
                entries_filenames.append(entries_filename)
        
        else: # If file exists, append most recent entries to it...
            # First, get the last ID in the CSV...
            last_time = get_last_line(entries_filename, 1).split(',')[2]
            last_time = parser.parse(last_time, tzinfos=get_tzinfos())
            
            update_entries_file(entries_filename, 
                                'a', 
                                entries_fields, 
                                filter_from=last_time)
            
            entries_filenames.append(entries_filename)
        
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
        
        zip_file(courts_zipname, courts_filename)
        zip_file(cases_zipname, cases_filename)
        
        # Zip every entries file we created or updated this run
        entries_zipnames = []
        for filename in entries_filenames:
            zipname = filename.replace('.csv', '.zip')
            zip_file(zipname, filename)
            entries_zipnames.append(zipname)
            
        # Used for tracking time it takes to create files, zip and then upload
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        logger.info('INFO - %s - Archive finished zipping files after %s' % ( 
                    time_ended, 
                    time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))
        
        # Now, we upload to Internet Archive
        uploaded = False
        if not options['noupload']:
            r = upload(settings.IA_IDENTIFIER, 
                       files=[courts_zipname, cases_zipname] + entries_zipnames, 
                       access_key=settings.IA_ACCESS_KEY, 
                       secret_key=settings.IA_SECRET_KEY,
                       # Retry on 503 Slow Down (archive.org S3 overloaded) instead of aborting the run
                       retries=10, retries_sleep=120)
            uploaded = all(response.status_code == 200 for response in r)
            if not uploaded:
                logger.error('ERROR - Archive upload returned %s' % 
                             ', '.join(str(response.status_code) for response in r))

        # Log stuff
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        logger.info('INFO - %s - Archive finished uploading after %s' % ( 
                    time_ended, 
                    time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))
        
        # Finally, drop entries older than the retention window. Only do this
        # when this run's upload succeeded, so the archive is always ahead of
        # the database.
        if options['noprune']:
            logger.info('INFO - Archive did not delete old entries (--noprune).')
        elif not uploaded:
            logger.warning('WARNING - Archive did not delete old entries because '
                           'nothing was uploaded this run.')
        else:
            self.prune(time_started)
    
    def prune(self, time_started):
        cutoff = get_retention_cutoff()
        deleted = prune_old_entries(cutoff)
        
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        logger.info('INFO - %s - Archive deleted %s entries captured before %s '
                    '(%s months) and finished after %s' % (
                    time_ended,
                    deleted,
                    cutoff.strftime('%Y-%m-%d %H:%M'),
                    ENTRY_RETENTION_MONTHS,
                    time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))
