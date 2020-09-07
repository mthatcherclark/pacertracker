# Create your views here.
import sys
from django.core import serializers
import simplejson

from django.http import HttpResponse, HttpResponseRedirect
from django.templatetags.static import static
from django.shortcuts import render, redirect
from django.contrib import auth
from django.contrib.auth.models import User
from django.forms.models import modelformset_factory
from django.forms import CheckboxSelectMultiple

from haystack.query import SearchQuerySet
from haystack.inputs import Clean

from pacertracker.forms import PasswordReset, AlertForm
from pacertracker.models import Alert, Court, CourtGroup, Case

def index(request):
    #Prepare user list needed by login shortcut
    user_list = User.objects.order_by('-last_name')
    context = {'user_list': user_list}
    return render(request, 'pacertracker/index.html', context)
    
def logout_view(request):
    auth.logout(request)
    return redirect('index')
    
def alerts(request):
    if not request.user.is_authenticated:
        return redirect('index')

    AlertFormSet = modelformset_factory(Alert, form=AlertForm, extra=1, max_num=100, can_delete=True)

    if request.method == 'POST':
        alert_form = AlertFormSet(request.POST, 
                                        queryset=Alert.objects.filter(user=request.user))
        if alert_form.is_valid():
            instances = alert_form.save(commit=False)
            for instance in instances:
                instance.user = request.user
                instance.save()
            alert_form.save_m2m()
            for object in alert_form.deleted_objects:
                object.delete()
            
            return redirect('alerts')
    else:
       alert_form = AlertFormSet(queryset=Alert.objects.filter(user=request.user).order_by('id'))
        
    court_groups = []
    court_group = {}
    for group in CourtGroup.objects.all().order_by('name'):
        court_group['id'] = group.id
        court_group['name'] = group.name
        court_group['court_array'] = str(list(group.courts.filter(has_feed=True).values_list('id', flat = True))
                                         ).replace('[','').replace(']','').replace(',','')
        court_groups.append(court_group)
        court_group = {}
    
    context = {
        'formset' : alert_form,
        'user' : request.user,
        'court_groups' : court_groups,
        }
    return render(request, 'pacertracker/alerts.html', context)
    
def case_lookup(request):
    # Default return list
    data = ''
    if request.method == "GET":
        if 'query' in request.GET and 'courts' in request.GET:
            value = request.GET[u'query']
            courts = request.GET[u'courts'].split(',')
            # Ignore blank queries or no courts
            if len(value) > 0 and (len(courts) > 0 and len(courts[0]) > 0):
                cases = SearchQuerySet().filter(content=value, court__in=courts)
                if 'type' in request.GET and (request.GET[u'type'] == '1CV' 
                    or request.GET[u'type'] == '2CR'):
                    cases = cases.exclude(type=request.GET[u'type'])
                results = simplejson.loads(
                    serializers.serialize(
                        'json', [q.object for q in cases[:30]], 
                                fields=('title','court'), 
                                use_natural_foreign_keys=True, 
                                use_natural_primary_keys=True))
                data = {}
                data['results'] = results
                data['count'] = cases.count()
                data = simplejson.dumps(data)

    return HttpResponse(data, content_type='application/json')
    
def change_password(request):
    if not request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        form = PasswordReset(request.user, request.POST)

        if form.is_valid():
            password2 = form.cleaned_data['password2']
            request.user.set_password(password2)
            request.user.save()
            auth.logout(request)
            return redirect('index')
    else:
        form = PasswordReset(request.user)
    return render(request, 'pacertracker/change_password_form.html', {
                  'form': form
                  })
