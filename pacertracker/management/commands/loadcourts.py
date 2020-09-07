import sys
import re
import requests
import datetime

from bs4 import BeautifulSoup
from concurrent import futures
from timeit import default_timer as timer
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from django.utils.timezone import utc
from django.core.management.base import BaseCommand, CommandError

from pacertracker.models import Court

def get_type(tag):
    if 'Supreme Court' in tag['alt']:
        type = 'S'
    elif 'Pacer Case' in tag['alt']:
        type = False
    elif '(web)' in tag['alt']:
        type = False
    elif '(asbestos)' in tag['alt']:
        type = False
    elif 'Bankruptcy Appellate Panel' in tag['alt']:
        type = False
    elif 'ECF' in tag['alt'] or 'NextGen' in tag['alt']:
        #This first conditional takes care of California courts,
        #which (like Appeals) have URLs containing ecf.ca
        if ('ecf.ca' in tag['href'] 
            and 'b.usc' not in tag['href'] 
            and 'd.usc' not in tag['href']):
            type = 'A'
        elif 'ecf.jpml' in tag['href']:
            type = 'M'
        elif 'ecf.cofc' in tag['href']:
            type = 'F'
        elif 'ecf.cit' in tag['href']:
            type = 'I'
        elif 'd.usc' in tag['href']:
            type = 'D'
        elif 'b.usc' in tag['href']:
            type = 'B'
    else:
        type = False
    
    return type

def get_name(tag):
    name = tag.string.replace('U.S. ', '').replace('  - ECF', '')
    name = name.replace('  - NextGen', '').replace('  - BAP', ' (BAP)').replace(' - BAP', ' (BAP)').strip()

    #This is necessary due to a spelling error on the court links page.
    if 'Multidistrict' in tag.string:
     name = 'Judicial Panel On Multidistrict Litigation'
    
    return name
    
def requests_retry_session(
    retries=5,
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
    
def check_feed(tag, feed_url):
    if feed_url != '' and 'BAP' not in tag.string:
        #Try to download the feed and see if it has entries
        try:
            response = requests_retry_session().get(
                feed_url,
                verify=False,
                timeout=60
            )
            feed = BeautifulSoup(response.content, "lxml-xml")
        except Exception as e:
            print('Connection error with: %s - %s' % (feed_url,e))
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
    
    #Even if the feed was not properly formatted, we need to mark
    #those courts that are listed as having a feed on the courts
    #website as having a feed
    if not feed_check and 'RSS' in str(tag.find_next('a')):
        feed_check = True
        publishes_all = False
        filing_types = ''

    return feed_check, publishes_all, filing_types
    
def update_court(tag):
    if get_type(tag):
        type = get_type(tag)
    else:
        print('Did not save %s.' % tag.string)
        return None
    
    name = get_name(tag)
    
    #Get base ECF URL
    base_ecf_url = tag['href'][:tag['href'].find('.gov') + 4] + '/'
    
    #Add the feed url even if it doesn't say it has a feed
    if (type == 'D' or type == 'B' or type == 'F' or type == 'I' or type == 'M'):
        feed_url = base_ecf_url + 'cgi-bin/rss_outside.pl'
    elif type == 'A':
        feed_url = base_ecf_url + 'cmecf/servlet/TransportRoom?servlet=RSSGenerator'
    else:
        feed_url = ''
        
    has_feed, publishes_all, filing_types = check_feed(tag, feed_url)

    website = base_ecf_url.replace('https://ecf','http://www')

    court_check = Court.objects.filter(website=website)
    
    if court_check.exists() and court_check.count() == 1:
        if has_feed and not court_check[0].has_feed:
            print('This court now has a feed: %s - %s' % (name, court_check[0].get_type_display()))
        if not has_feed and court_check[0].has_feed:
            print('This court no longer has a feed: %s - %s' % (name, court_check[0].get_type_display()))
        court_check.update(name=name, type=type, has_feed=has_feed, feed_url=feed_url, website=website,
                            publishes_all=publishes_all, filing_types=filing_types)
    else:
        #To ensure all entries from current RSS files are retrieved when first scraped for new courts,
        #we set the last_updated to one year ago (roughly).
        last_updated = datetime.datetime.utcnow().replace(tzinfo=utc) - datetime.timedelta(days=365)
        court, new = Court.objects.get_or_create(name=name, type=type, 
                    has_feed=has_feed, feed_url=feed_url, website=website,
                    last_updated=last_updated, publishes_all=publishes_all, 
                    filing_types=filing_types)
        if not new:
            print('Could not save %s.' % name)
        else:
            print('Added this court: %s' % name)
    
    return None


class Command(BaseCommand):
    args = 'No args.'
    help = 'Download court feeds and store docket data.'

    def handle(self, *args, **options):
        print(datetime.datetime.now())
        start = timer()
        
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    
        response = requests.get('http://www.pacer.gov/psco/cgi-bin/links.pl')
        soup = BeautifulSoup(response.text, 'lxml')
        
        a_tags = soup.find_all('a',class_='jtip')
        
        #Update the courts
        with futures.ThreadPoolExecutor(max_workers=15) as executor:
            results = executor.map(update_court, a_tags)
            
        end = timer()
        print(end-start)