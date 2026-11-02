# Create your views here.
import logging
import sys
from django.core import serializers
import simplejson

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.templatetags.static import static
from django.shortcuts import render, redirect
from django.contrib import auth, messages
from django.contrib.auth.models import User, Group
from django.contrib.auth.views import PasswordResetConfirmView
from django.forms.models import modelformset_factory
from django.forms import formset_factory, CheckboxSelectMultiple
from django.utils.crypto import get_random_string

from haystack.query import SearchQuerySet
from haystack.inputs import Clean

from pacertracker.forms import PasswordReset, AlertForm, CourtSelectMultiple
from pacertracker.forms import (REVOKED_GROUP, domain_for, NewUserForm,
    BaseNewUserFormSet, AccountPasswordResetForm, ReactivatingSetPasswordForm,
    DeleteAccountForm)
from pacertracker.models import Alert, Court, CourtGroup, Case

logger = logging.getLogger(__name__)

def index(request):
    return render(request, 'pacertracker/index.html')
    
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
    for group in CourtGroup.objects.filter(user=request.user).order_by('name'):
        court_group['id'] = group.id
        court_group['name'] = group.name
        court_group['court_array'] = str(list(group.courts.values_list('id', flat = True))
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
    
def groups(request):
    if not request.user.is_authenticated:
        return redirect('index')
        
        
    CourtGroupFormSet = modelformset_factory(CourtGroup, 
                                             fields={'name','courts'},
                                             extra=1,
                                             max_num=5, 
                                             can_delete=True,
                                             widgets={'courts': CourtSelectMultiple()},)

    if request.method == 'POST':
        formset = CourtGroupFormSet(request.POST, 
                                    queryset=CourtGroup.objects.filter(user=request.user).order_by('id'))
        if formset.is_valid():
            instances = formset.save(commit=False)
            for instance in instances:
                instance.user = request.user
                instance.save()
            formset.save_m2m()
            for object in formset.deleted_objects:
                object.delete()
            
            return redirect('alerts')
    else:
       formset = CourtGroupFormSet(queryset=CourtGroup.objects.filter(user=request.user).order_by('id'))
    
    return render(request, 'pacertracker/group_form.html', 
                  {'formset': formset}
                  )
    
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


def manageable_users(actor):
    """The accounts this user is allowed to add to, switch off or re-invite.

    Staff and superusers see everyone. A delegate sees only their own domain,
    and never staff, superusers or themselves, so they can neither remove an
    administrator nor lock themselves out.
    """
    domain = domain_for(actor)

    if domain is None:
        return User.objects.all().order_by('username')

    if not domain:
        return User.objects.none()

    return (User.objects.filter(email__iendswith='@' + domain)
                        .exclude(is_staff=True)
                        .exclude(is_superuser=True)
                        .exclude(pk=actor.pk)
                        .order_by('username'))


def send_invite(user, request):
    """Send the welcome email, which is a password reset under the covers."""
    form = AccountPasswordResetForm({'email': user.email})

    if form.is_valid():
        form.save(request=request,
                  use_https=True,
                  from_email=settings.DEFAULT_FROM_EMAIL,
                  subject_template_name='pacertracker/new_account_subject.txt',
                  html_email_template_name='pacertracker/new_account_email_body.html')


def add_user(request):
    if not request.user.is_authenticated:
        return redirect('index')
    if not request.user.has_perm('auth.add_user'):
        raise PermissionDenied

    domain = domain_for(request.user)

    #A delegate with no email address of their own has no domain to work in.
    if domain == '':
        return render(request, 'pacertracker/user_add_form.html', {'no_domain': True})

    NewUserFormSet = formset_factory(NewUserForm, formset=BaseNewUserFormSet, extra=3)

    if request.method == 'POST':
        formset = NewUserFormSet(request.POST, form_kwargs={'actor': request.user})

        if formset.is_valid():
            created = []

            with transaction.atomic():
                for form in formset:
                    if not form.has_changed():
                        continue

                    email = form.cleaned_data['email']
                    user = User(username=email,
                                email=email,
                                first_name=form.cleaned_data['first_name'],
                                last_name=form.cleaned_data['last_name'],
                                is_active=True,
                                is_staff=False,
                                is_superuser=False)
                    #Nobody ever sees this password. New users set their own
                    #through the link in the welcome email.
                    user.set_password(get_random_string(50))
                    user.save()

                    created.append(user)
                    logger.info('Account created: %s by %s',
                                user.username, request.user.username)

                #Only send once the whole batch is safely saved.
                for user in created:
                    transaction.on_commit(
                        lambda user=user: send_invite(user, request))

            if created:
                messages.success(request, 'Created %s account(s): %s. '
                    'Each person has been emailed a link to set their password.'
                    % (len(created), ', '.join(u.username for u in created)))
            else:
                messages.error(request, 'Nothing to add. Fill in at least one row.')

            return redirect('add_user')
    else:
        formset = NewUserFormSet(form_kwargs={'actor': request.user})

    return render(request, 'pacertracker/user_add_form.html',
                  {'formset': formset, 'domain': domain})


def manage_users(request):
    if not request.user.is_authenticated:
        return redirect('index')
    if not request.user.has_perm('auth.change_user'):
        raise PermissionDenied

    domain = domain_for(request.user)

    if domain == '':
        return render(request, 'pacertracker/user_manage.html', {'no_domain': True})

    users = manageable_users(request.user)

    if request.method == 'POST':
        #Filtering the chosen ids back through the same queryset is what keeps
        #a delegate from touching an account outside their domain.
        targets = list(users.filter(pk__in=request.POST.getlist('users')))
        action = request.POST.get('action')

        if not targets:
            messages.error(request, 'No accounts were selected.')
        elif action == 'deactivate':
            revoked = Group.objects.get_or_create(name=REVOKED_GROUP)[0]

            for user in targets:
                user.is_active = False
                user.save(update_fields=['is_active'])
                user.groups.add(revoked)
                logger.info('Account deactivated: %s by %s',
                            user.username, request.user.username)

            messages.success(request, 'Switched off %s account(s): %s.'
                % (len(targets), ', '.join(u.username for u in targets)))
        elif action == 'reinvite':
            revoked = Group.objects.get_or_create(name=REVOKED_GROUP)[0]

            for user in targets:
                user.is_active = True
                user.set_password(get_random_string(50))
                user.save()
                #Has to come off the revoked list before the email is sent,
                #or the reset form will skip them.
                user.groups.remove(revoked)
                send_invite(user, request)
                logger.info('Account re-invited: %s by %s',
                            user.username, request.user.username)

            messages.success(request, 'Re-invited %s account(s): %s. '
                'Each person has been emailed a link to set a new password.'
                % (len(targets), ', '.join(u.username for u in targets)))
        else:
            messages.error(request, 'Choose what to do with the accounts you picked.')

        query = request.GET.urlencode()
        return redirect(request.path + ('?' + query if query else ''))

    search = request.GET.get('q', '').strip()
    #Active accounts are what you nearly always want to see, so they are the
    #default. The switched off ones are one button away.
    showing_off = request.GET.get('status') == 'off'

    users = users.filter(is_active=not showing_off)

    if search:
        users = users.filter(Q(username__icontains=search)
                             | Q(first_name__icontains=search)
                             | Q(last_name__icontains=search))

    return render(request, 'pacertracker/user_manage.html',
                  {'accounts': users,
                   'domain': domain,
                   'search': search,
                   'showing_off': showing_off,
                   'query': request.GET.urlencode()})


def delete_account(request):
    if not request.user.is_authenticated:
        return redirect('index')

    #Administrators would lock themselves out of the admin site.
    if request.user.is_staff or request.user.is_superuser:
        raise PermissionDenied

    if request.method == 'POST':
        form = DeleteAccountForm(request.user, request.POST)

        if form.is_valid():
            user = request.user
            logger.info('Account deleted by its owner: %s (%s alerts, %s court groups)',
                        user.username,
                        Alert.objects.filter(user=user).count(),
                        CourtGroup.objects.filter(user=user).count())

            auth.logout(request)
            user.delete()

            messages.success(request, 'Your account has been deleted.')

            return redirect('index')
    else:
        form = DeleteAccountForm(request.user)

    return render(request, 'pacertracker/account_delete_form.html',
                  {'form': form,
                   'alert_count': Alert.objects.filter(user=request.user).count(),
                   'group_count': CourtGroup.objects.filter(user=request.user).count()})


class AccountPasswordResetConfirmView(PasswordResetConfirmView):
    """Reset links work for lapsed accounts, but never for revoked ones.

    Switching an account off does not change the password or the last login,
    so a link mailed out before that still validates for its full three days.
    Checking here closes that window.
    """
    form_class = ReactivatingSetPasswordForm

    def get_user(self, uidb64):
        user = super(AccountPasswordResetConfirmView, self).get_user(uidb64)

        if user is not None and user.groups.filter(name=REVOKED_GROUP).exists():
            return None

        return user
