import sys
import re
import requests
import datetime
import logging
import json

from bs4 import BeautifulSoup
from concurrent import futures
from timeit import default_timer as timer
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from django.core.management.base import BaseCommand, CommandError

from pacertracker.models import Court

utc = datetime.timezone.utc
logger = logging.getLogger(__name__)

def get_type(raw_name, ecf_url):
    if 'Supreme Court' in raw_name:
        type = 'S'
    elif 'Pacer Case' in raw_name: # Not a court
        type = 'BAD'
    elif '(web)' in raw_name:
        type = 'BAD'
    elif '(asbestos)' in raw_name: # Does not have a feed
        type = 'BAD'
    elif 'BAP' in raw_name: # Does not have a feed
        type = 'BAD'
    elif ('ecf.ca' in ecf_url
        and 'b.usc' not in ecf_url 
        and 'd.usc' not in ecf_url):
        #This conditional takes care of California courts,
        #which (like Appeals) have URLs containing ecf.ca
        type = 'A'
    elif 'ecf.jpml' in ecf_url:
        type = 'M'
    elif 'ecf.cofc' in ecf_url:
        type = 'F'
    elif 'ecf.cit' in ecf_url:
        type = 'I'
    elif 'd.usc' in ecf_url:
        type = 'D'
    elif 'b.usc' in ecf_url:
        type = 'B'
    else:
        type = False
    
    return type

def get_name(raw_name):
    name = raw_name.replace('U.S. Court of ', '').replace('Appeals, ', '')
    name = name.replace(' Bankruptcy Court', '').replace(' District Court', '')
    name = name.replace(' of the United States', '').replace(' Bankruptcy','').strip()
    
    return name
    
def requests_retry_session(
    retries=3,
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
    
def check_feed(json_check, feed_url):
    if feed_url != '':
        # Try to download the feed and see if it has entries
        try:
            response = requests_retry_session().get(
                feed_url,
                verify=False,
                timeout=5
            )
            feed = BeautifulSoup(response.content, "lxml-xml")
        except requests.exceptions.ConnectionError as e:
            # Max Retries Exceeded
            feed = None

        if feed and (not feed.channel or not feed.title or '404' in feed.title.text):
            feed_check = False
            publishes_all = False
            filing_types = ''
        elif feed and feed.channel.description and 'not configured' in feed.channel.description.text:
            feed_check = False
            publishes_all = False
            filing_types = ''
        elif feed and feed.channel.description:
            feed_check = True
            filing_types = feed.channel.description.text
            
            if (len(filing_types) > 24 and 'all' in filing_types[24:].lower()
                and 'entries of type' in filing_types):
                publishes_all = True
                filing_types = 'All filings'
            elif (len(filing_types) > 24 and filing_types[24:] != '' 
                  and 'entries of type' not in filing_types):
                publishes_all = False
            elif len(filing_types) > 24 and filing_types[24:] != '':
                publishes_all = False
                filing_types = filing_types[24:]
            else:
                publishes_all = False
                filing_types = ''
        else:
            feed_check = False
            publishes_all = False
            filing_types = ''
    else:
        feed_check = False
        publishes_all = False
        filing_types = ''
    
    # Even if the feed was not properly formatted,
    # we still need to mark in PACER Tracker those courts that 
    # are listed as having a feed in the JSON.
    # This may be necessary when feeds temporarily go down
    # during the period loadcourts checks them.
    if not feed_check and json_check:
        feed_check = True
        publishes_all = False
        filing_types = ''

    return feed_check, publishes_all, filing_types
    
def update_court(metadata):
    raw_name = metadata['title']
    if 'Supreme Court' in raw_name:
        # Supreme Court has no base_ecf_url so we just give it a fake one...
        base_ecf_url = 'https://ecf.supremecourt.gov/'
    else:
        base_ecf_url = metadata['login_url']
        if base_ecf_url[-1] != '/':
            base_ecf_url += '/'
    
    type = get_type(raw_name, base_ecf_url)
    
    if not type:
        error_msg = 'WARNING - %s - Loadcourts did not save %s. Could not get court type.'
        error_msg = (error_msg % (datetime.datetime.utcnow().replace(tzinfo=utc),
                     raw_name
                     ))
        logger.warning(error_msg)
        return None
    elif type == 'BAD':
        return None # For links to no-feed courts or the PACER case locator
    
    # If the JSON has an RSS URL, that does not mean it has
    # an RSS feed and also may mean that it has a "hidden" one
    # So, we use it as one indicator of a feed
    json_check = True if 'rss_url' in metadata else False
    
    # Truncates names to jurisdiction
    name = get_name(raw_name)
    
    # Add the feed url even if it doesn't say it has a feed
    if (type == 'D' or type == 'B' or type == 'F' or type == 'I' or type == 'M'):
        feed_url = base_ecf_url + 'cgi-bin/rss_outside.pl'
    elif type == 'A':
        feed_url = base_ecf_url + 'cmecf/servlet/TransportRoom?servlet=RSSGenerator'
    else:
        feed_url = ''
    
    has_feed, publishes_all, filing_types = check_feed(json_check, feed_url)
    
    website = base_ecf_url.replace('https://ecf','http://www')
    
    court_check = Court.objects.filter(website=website)
    
    if court_check.exists() and court_check.count() == 1:
        if has_feed and not court_check[0].has_feed and 'nyed' not in feed_url:
            info_msg = 'INFO - %s - Loadcourts found this court now has a feed: %s - %s.'
            info_msg = (info_msg % (datetime.datetime.utcnow().replace(tzinfo=utc),
                         name,
                         court_check[0].get_type_display()
                         ))
            logger.info(info_msg)
            
        elif not has_feed and court_check[0].has_feed and 'nyed' not in feed_url: # See below about NYED
            warning_msg = 'WARNING - %s - Loadcourts found this court no longer has a feed: %s - %s.'
            warning_msg = (warning_msg % (datetime.datetime.utcnow().replace(tzinfo=utc),
                         name,
                         court_check[0].get_type_display()
                         ))
            logger.warning(warning_msg)
        
        # New York Eastern District Court has a different feed URL from all other courts
        # https://ecf.nyed.uscourts.gov/cgi-bin/readyDockets.pl
        # As such, we use the below code to overwrite the above checks
        if 'nyed' not in feed_url: # This ensures the NYED keeps its fancy one-off URL
            court_check.update(name=name, type=type, has_feed=has_feed, feed_url=feed_url, website=website,
                                publishes_all=publishes_all, filing_types=filing_types)
            
    else:
        #To ensure all entries from current RSS files are retrieved when first scraped for new courts,
        #we set the last_updated to one year ago (roughly).
        last_updated = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc) - datetime.timedelta(days=365)
        court, new = Court.objects.get_or_create(name=name, type=type, 
                    has_feed=has_feed, feed_url=feed_url, website=website,
                    last_updated=last_updated, publishes_all=publishes_all, 
                    filing_types=filing_types)
        if not new:
            info_msg = 'INFO - %s - Loadcourts found this court was already entered, possibly more than once: %s - %s.'
            info_msg = (info_msg % (datetime.datetime.utcnow().replace(tzinfo=utc),
                         type,
                         name
                         ))
            logger.info(info_msg)
        elif new and not has_feed:
            info_msg = 'INFO - %s - Loadcourts added this court, but it has no feed: %s - %s.'
            info_msg = (info_msg % (datetime.datetime.utcnow().replace(tzinfo=utc),
                         type,
                         name
                         ))
            logger.info(info_msg)
        else:
            info_msg = 'INFO - %s - Loadcourts added this court: %s - %s.'
            info_msg = (info_msg % (datetime.datetime.utcnow().replace(tzinfo=utc),
                         type,
                         name
                         ))
            logger.info(info_msg)
    
    return None


class Command(BaseCommand):
    args = 'No args.'
    help = 'Load and update the status of each federal court RSS feed.'

    def handle(self, *args, **options):
        time_started = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

        response = requests.get('https://pacer.uscourts.gov/file-case/court-cmecf-lookup/data.json')
        json_metadata = json.loads(response.text)
        json_metadata = json_metadata['data']
        
        # Add or update courts
        with futures.ThreadPoolExecutor(max_workers=15) as executor:
            results = []
            for metadata in json_metadata:
                results.append(
                    executor.submit(
                        update_court, metadata
                    )
                )
            for result in futures.as_completed(results):
                try:
                    the_result = result.result(timeout=16) # Needed to trickle down exception
                except Exception as exc:
                    raise exc
        
        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')
        time_ended = datetime.datetime.utcnow().replace(tzinfo=utc)
        logger.info('INFO - %s - Loadcourts finished after %s' % ( 
                    time_ended, 
                    time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' seconds'))
