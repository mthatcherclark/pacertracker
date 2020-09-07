import datetime
from haystack import indexes
from pacertracker.models import Case

#For sendemails, we need court, title, type, is_date_filed, captured_time
class CaseIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, model_attr='title')
    court = indexes.IntegerField(model_attr='court__id')
    captured_time = indexes.DateTimeField(model_attr='captured_time')
    updated_time = indexes.DateTimeField(model_attr='updated_time')
    type = indexes.CharField(model_attr='type')
    is_date_filed = indexes.BooleanField(model_attr='is_date_filed')

    def get_model(self):
        return Case
        
    def get_updated_field(self):
        return "updated_time"
