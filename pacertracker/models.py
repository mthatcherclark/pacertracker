import uuid

from django.db import models
from django.contrib.auth.models import User

class Alert(models.Model):
    #The blank choice is needed for the alerts page form
    DISTRICT_FILTER = (
        ('', 'Criminal and civil cases'),
        ('1CV', 'Only criminal cases'),
        ('2CR', 'Only civil cases'),
    )
    user = models.ForeignKey(User, editable=False, on_delete=models.CASCADE)
    words = models.CharField(max_length=75, blank=True)
    courts = models.ManyToManyField('Court')
    district_court_filter = models.CharField(max_length=3, choices=DISTRICT_FILTER, blank=True)
    only_new_cases = models.BooleanField(default=False)
    live_updates = models.BooleanField(default=False)
    last_checked = models.DateTimeField(auto_now_add=True, editable=False)

    def __str__(self):
        return self.user.username + ' - '+ self.words

class Court(models.Model):
    COURT_TYPES = (
        ('S', 'Supreme Court'),
        ('A', 'Appeals Court'),
        ('M', 'Judicial Panel on Multidistrict Litigation'),
        ('F', 'Federal Claims Court'),
        ('I', 'International Trade Court'),
        ('D', 'District Court'),
        ('B', 'Bankruptcy Court'),
    )
    name = models.CharField(max_length=75)
    type = models.CharField(max_length=1, choices=COURT_TYPES, default='D')
    has_feed = models.BooleanField(default=False)
    publishes_all = models.BooleanField(default=False)
    filing_types = models.CharField(max_length=2000, blank=True)
    feed_url = models.URLField(max_length=2000, blank=True)
    website = models.URLField(max_length=2000)
    last_updated = models.DateTimeField(editable=False, blank=True, null=True,
        help_text='Date and time from the court\'s clock.')

    class Meta:
        ordering = ['type','name']

    def __str__(self):
        return self.get_type_display() + ': ' + self.name
    
    def natural_key(self):
        return (self.type, self.name)


class CourtGroup(models.Model):
    name = models.CharField(max_length=75)
    courts = models.ManyToManyField('Court')

    def __str__(self):
        return self.name


class Case(models.Model):
    CASE_TYPES = (
        ('1CV', 'Civil'),
        ('2CR', 'Criminal'),
        ('3BK', 'Bankruptcy'),
        ('4AP', 'Appeals'),
        ('5MD', 'Multi-District Litigation'),
        ('6VC', 'Vaccine'),
        ('7CG', 'Congressional Record'),
    )
    id = models.BigIntegerField(primary_key=True, editable=False) # CHANGE THIS TO PRIMARY KEY AND THEN MODIFY CODE
    court = models.ForeignKey('Court', on_delete=models.CASCADE)
    title = models.CharField(max_length=500)
    number = models.CharField(max_length=50)
    name = models.CharField(max_length=500)
    type = models.CharField(max_length=3, choices=CASE_TYPES)
    website = models.URLField(max_length=2000, help_text='The case\'s docket report site.')
    captured_time = models.DateTimeField(auto_now_add=True, editable=False)
    updated_time = models.DateTimeField(auto_now=True)
    is_date_filed = models.BooleanField(default=False, 
        help_text='Is captured_time the date (but not the time) case was filed? Note: time is used for filtering.')

    def __str__(self):
        return self.title


class Entry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey('Case', on_delete=models.CASCADE)
    time_filed = models.DateTimeField(help_text='According to court\'s clock.', editable=False)
    captured_time = models.DateTimeField(auto_now_add=True, editable=False)
    description = models.CharField(max_length=500)
    number = models.IntegerField(blank=True, null=True, help_text='Document number, if available.')
    website = models.URLField(max_length=2000, blank=True, null=True)

    class Meta:
        verbose_name_plural = 'entries'

    def __str__(self):
        return self.description

