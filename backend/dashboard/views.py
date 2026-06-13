import json
import os
import re
from django.db.models import Count
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string
from django.utils.html import escape
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from channels_app.models import TeamChannel
from chat.models import ChatMessage
from accounts.models import CustomUser
from notifications.models import Notification


def _member_subtitle(members, request_user):
    """Formats member names like WhatsApp: 'You, Anuj, Prince, Mukesh...'."""
    names = []
    for m in members:
        if m.id == request_user.id:
            names.append('You')
        else:
            names.append(m.username.capitalize())
    return ', '.join(names)


def _format_preview(text):
    """Convert raw message text into a human-readable sidebar preview."""
    if not text:
        return ''
    if text.startswith('[ANN]'):
        try:
            data = json.loads(text[5:])
            title = data.get('title', '').strip()
            if title:
                return '\U0001f4e2 Announcement: ' + title
            return '\U0001f4e2 Announcement'
        except (json.JSONDecodeError, IndexError):
            return '\U0001f4e2 Announcement'
    if text.startswith('[TASK]'):
        try:
            data = json.loads(text[6:])
            title = data.get('title', '').strip()
            if title:
                return '\U0001f4dd Task: ' + title
            return '\U0001f4dd Assigned Task'
        except (json.JSONDecodeError, IndexError):
            return '\U0001f4dd Assigned Task'
    if text.startswith('[EVENT]'):
        try:
            data = json.loads(text[7:])
            name = data.get('name', '').strip()
            if name:
                return '\U0001f4c5 ' + name
            return '\U0001f4c5 Event Created'
        except (json.JSONDecodeError, IndexError):
            return '\U0001f4c5 Event Created'
    if text.startswith('[LOC]'):
        return '\U0001f4cd Live Location'
    if text.startswith('__voice__'):
        return '\U0001f3a4 Voice Message'
    return text


def _dm_preview_data(current_user):
    """Returns a dict of dm-slug -> {preview, latest_at} for the current user's DMs."""
    dm_channels = TeamChannel.objects.filter(
        slug__startswith='dm-', members=current_user
    ).annotate(member_count=Count('members'))
    result = {}
    for ch in dm_channels:
        # Normalize slug to canonical form (min-max)
        parts = ch.slug.split('-')
        if len(parts) == 3:
            try:
                uid1, uid2 = int(parts[1]), int(parts[2])
                norm_slug = f'dm-{min(uid1, uid2)}-{max(uid1, uid2)}'
            except ValueError:
                norm_slug = ch.slug
        else:
            norm_slug = ch.slug

        qs = ChatMessage.objects.filter(
            channel=ch, is_deleted_for_everyone=False
        ).exclude(deleted_for=current_user)
        latest = qs.order_by('-created_at').select_related('sender').first()
        if not latest:
            if norm_slug not in result:
                result[norm_slug] = {'preview': '', 'latest_at': None}
            continue
        if latest.sender_id == current_user.id:
            sender_name = 'You'
        else:
            full_name = latest.sender.get_full_name().strip()
            sender_name = full_name if full_name else latest.sender.username.capitalize()
        if latest.message:
            text = _format_preview(latest.message)
        elif latest.image:
            text = '\U0001f5bc\ufe0f Photo'
        elif latest.file:
            text = '\U0001f4c4 ' + latest.file.name.split('/')[-1]
        else:
            if norm_slug not in result:
                result[norm_slug] = {'preview': '', 'latest_at': None}
            continue
        preview_text = (text[:50] + '...') if len(text) > 50 else text
        existing = result.get(norm_slug)
        if existing and existing['latest_at']:
            # Keep the most recent preview
            if latest.created_at and existing['latest_at'] < latest.created_at.isoformat():
                result[norm_slug] = {
                    'preview': f'{sender_name}: {preview_text}',
                    'latest_at': latest.created_at.isoformat(),
                }
        else:
            result[norm_slug] = {
                'preview': f'{sender_name}: {preview_text}',
                'latest_at': latest.created_at.isoformat(),
            }
    return result


def _latest_message_data(channel, current_user=None):
    """Returns preview + metadata for a channel's latest visible message."""
    qs = ChatMessage.objects.filter(
        channel=channel, is_deleted_for_everyone=False
    )
    if current_user:
        qs = qs.exclude(deleted_for=current_user)
    latest = qs.order_by('-created_at').select_related('sender').first()
    if not latest:
        return {
            'preview': '', 'latest_at': None,
            'latest_message_text': '', 'latest_message_sender_name': '',
            'latest_message_sender_id': None, 'latest_message_time': None,
            'latest_message_type': '',
        }
    if current_user and latest.sender_id == current_user.id:
        sender_name = 'You'
    else:
        full_name = latest.sender.get_full_name().strip()
        sender_name = full_name if full_name else latest.sender.username.capitalize()
    if latest.message:
        text = _format_preview(latest.message)
        msg_type = 'text'
    elif latest.image:
        text = '\U0001f5bc\ufe0f Photo'
        msg_type = 'image'
    elif latest.file:
        text = '\U0001f4c4 ' + latest.file.name.split('/')[-1]
        msg_type = 'file'
    else:
        return {
            'preview': '', 'latest_at': None,
            'latest_message_text': '', 'latest_message_sender_name': '',
            'latest_message_sender_id': None, 'latest_message_time': None,
            'latest_message_type': '',
        }
    preview_text = (text[:50] + '...') if len(text) > 50 else text
    return {
        'preview': f'{sender_name}: {preview_text}',
        'latest_at': latest.created_at.isoformat(),
        'latest_message_text': preview_text,
        'latest_message_sender_name': sender_name,
        'latest_message_sender_id': latest.sender_id,
        'latest_message_time': latest.created_at.isoformat(),
        'latest_message_type': msg_type,
    }


def login_view(request):
    if request.user.is_authenticated:
        if hasattr(request, '_st'):
            return redirect(f'/?_st={request._st}')
        return redirect('dashboard_home')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if hasattr(request, '_st'):
                return redirect(f'/?_st={request._st}')
            return redirect('dashboard_home')
        else:
            messages.error(request, 'Invalid username or password')

    return render(request, 'login.html', {'MEDIA_URL': settings.MEDIA_URL})


def _active_channels_qs(user):
    """Base queryset of active (not archived, not deleted) non-DM channels for the user."""
    qs = TeamChannel.objects.filter(is_archived=False, is_deleted=False).exclude(slug__startswith='dm-')
    if user.role == 'admin':
        return qs
    if user.role == 'management':
        return qs
    return qs.filter(members=user)


def _archived_channels_qs(user):
    """Archived (but not deleted) non-DM channels visible to admin/management."""
    if user.role == 'employee':
        return TeamChannel.objects.none()
    return TeamChannel.objects.filter(is_archived=True, is_deleted=False).exclude(slug__startswith='dm-')


def _deleted_channels_qs(user):
    """Recently deleted non-DM channels — admin only."""
    if user.role != 'admin':
        return TeamChannel.objects.none()
    return TeamChannel.objects.filter(is_deleted=True).exclude(slug__startswith='dm-')


def dashboard_home(request):
    user = request.user

    if user.role == 'admin':
        active = _active_channels_qs(user)
        if not active.exists():
            for name in ['General', 'Admin', 'Management']:
                ch, created = TeamChannel.objects.get_or_create(name=name, defaults={'slug': slugify(name)})
                if created:
                    mgmt_users = CustomUser.objects.filter(role='management')
                    ch.members.add(*mgmt_users)
            active = _active_channels_qs(user)
        active = active.annotate(member_count=Count('members'))
        all_users = CustomUser.objects.all()
    elif user.role == 'management':
        active = _active_channels_qs(user)
        for ch in active:
            if not ch.members.filter(id=user.id).exists():
                ch.members.add(user)
        active = active.annotate(member_count=Count('members'))
        all_users = CustomUser.objects.all()
    else:
        active = _active_channels_qs(user).annotate(member_count=Count('members'))
        all_users = CustomUser.objects.exclude(role='admin')

    archived = _archived_channels_qs(user).annotate(member_count=Count('members'))
    deleted = _deleted_channels_qs(user).annotate(member_count=Count('members'))

    unread_counts = Notification.objects.filter(
        user=user, channel__in=active, is_read=False
    ).values('channel__slug').annotate(count=Count('id'))
    unread_map = {item['channel__slug']: item['count'] for item in unread_counts}

    context = {
        'channels': active,
        'all_users_json': json.dumps([{
            'id': u.id, 'username': u.username, 'role': u.role,
            'initial': u.username[0].upper(), 'email': u.email or '',
            'department': u.department or '', 'about': u.about or '',
            'profile_pic_url': u.profile_pic_url(),
            'last_seen': u.last_seen.isoformat() if u.last_seen else None,
            'is_active': u.is_active
        } for u in all_users]),
        'channels_json': json.dumps([{
            'name': c.name, 'slug': c.slug, 'description': c.description or '',
            'profile_pic_url': c.profile_pic_url, 'member_count': c.member_count,
            'member_names': _member_subtitle(c.members.all(), request.user),
            'member_ids': [m.id for m in c.members.all()],
            'unread': unread_map.get(c.slug, 0),
            'is_archived': c.is_archived,
            'is_deleted': c.is_deleted,
            **_latest_message_data(c, request.user)
        } for c in active]),
        'archived_channels_json': json.dumps([{
            'name': c.name, 'slug': c.slug, 'description': c.description or '',
            'profile_pic_url': c.profile_pic_url, 'member_count': c.member_count,
            'member_names': _member_subtitle(c.members.all(), request.user),
            'member_ids': [m.id for m in c.members.all()],
            'is_archived': True, 'is_deleted': False,
            **_latest_message_data(c, request.user)
        } for c in archived]),
        'deleted_channels_json': json.dumps([{
            'name': c.name, 'slug': c.slug, 'description': c.description or '',
            'profile_pic_url': c.profile_pic_url, 'member_count': c.member_count,
            'member_names': _member_subtitle(c.members.all(), request.user),
            'member_ids': [m.id for m in c.members.all()],
            'is_deleted': True,
            'deleted_at': c.deleted_at.isoformat() if c.deleted_at else None,
            **_latest_message_data(c, request.user)
        } for c in deleted]),
        'active_channel': None,
        'messages': [],
        'channel_members': [],
        'member_subtitle': '',
        'unread_map_json': json.dumps(unread_map),
        'dm_preview_json': json.dumps(_dm_preview_data(request.user)),
        'MEDIA_URL': settings.MEDIA_URL,
        'channel_member_ids_json': '[]',
        'unread_mentions': Notification.objects.filter(user=user, type='mention', is_read=False).count(),
        'scroll_to_msg': '',
    }

    return render(request, 'channel_detail.html', context)


@login_required
def channel_detail(request, slug):
    user = request.user

    # Handle DM channels - create on demand if needed
    if slug.startswith('dm-'):
        parts = slug.split('-')
        if len(parts) == 3:
            try:
                uid1 = int(parts[1])
                uid2 = int(parts[2])
                # Normalize slug: always min-max order
                norm_uid1 = min(uid1, uid2)
                norm_uid2 = max(uid1, uid2)
                norm_slug = f'dm-{norm_uid1}-{norm_uid2}'
                other_id = norm_uid2 if norm_uid1 == user.id else norm_uid1
                other_user = get_object_or_404(CustomUser, id=other_id)
                ch, created = TeamChannel.objects.get_or_create(
                    slug=norm_slug,
                    defaults={'name': f'DM-{norm_uid1}-{norm_uid2}'}
                )
                if created:
                    # Only check DM permissions when creating a NEW DM channel
                    if user.role == 'employee':
                        emp_dept = (other_user.department or '').lower()
                        if emp_dept not in ('hr', 'finance', 'human resources'):
                            ch.delete()
                            messages.error(request, 'Employees can only send messages to HR and Finance.')
                            return redirect('dashboard_home')
                    elif user.role == 'admin' and other_user.role != 'management':
                        ch.delete()
                        messages.error(request, 'Admins can only DM management users.')
                        return redirect('dashboard_home')
                    elif user.role == 'management' and other_user.role not in ('employee', 'admin'):
                        ch.delete()
                        messages.error(request, 'Management can only DM employees and admins.')
                        return redirect('dashboard_home')
                    ch.members.add(norm_uid1, norm_uid2)
                # If the old non-canonical slug exists, merge it
                if slug != norm_slug:
                    old_ch = TeamChannel.objects.filter(slug=slug).first()
                    if old_ch and old_ch.id != ch.id:
                        # Move messages from old channel to canonical one
                        ChatMessage.objects.filter(channel=old_ch).update(channel=ch)
                        ch.members.add(*old_ch.members.all())
                        old_ch.delete()
                active_channel = ch
                # Set display name to the other user's name
                try:
                    other_user = CustomUser.objects.get(id=other_id)
                    active_channel.name = other_user.get_full_name() or other_user.username.capitalize()
                except CustomUser.DoesNotExist:
                    pass
            except (ValueError, IndexError):
                return redirect('dashboard_home')
        else:
            return redirect('dashboard_home')
    else:
        active_channel = get_object_or_404(TeamChannel, slug=slug)
        if active_channel.is_deleted:
            return redirect('dashboard_home')
        if user.role == 'employee' and active_channel.slug == 'admin':
            return redirect('dashboard_home')
        if user.role not in ['admin', 'management'] and active_channel.slug == 'management':
            return redirect('dashboard_home')
        if user.role == 'management' and not active_channel.members.filter(id=user.id).exists():
            active_channel.members.add(user)

    # HTMX request: return messages + OOB header updates (skip heavy queries)
    if request.headers.get('Hx-Request') == 'true':
        messages_list = ChatMessage.objects.filter(
            channel=active_channel, is_deleted_for_everyone=False
        ).exclude(deleted_for=request.user).select_related('sender', 'reply_to__sender')[:25]
        Notification.objects.filter(user=user, channel=active_channel, is_read=False).update(is_read=True)
        msgs_html = render_to_string('_msgs.html', {'messages': messages_list}, request=request)

        # Build OOB header updates
        is_dm = slug.startswith('dm-')
        if is_dm:
            parts = slug.split('-')
            uid1, uid2 = int(parts[1]), int(parts[2])
            other_id = uid2 if uid1 == user.id else uid1
            try:
                other = CustomUser.objects.get(id=other_id)
                title = other.get_full_name() or other.username.capitalize()
                subtitle = other.get_role_display()
                if other.profile_pic_url():
                    avatar = f'<img src="{other.profile_pic_url()}" class="hdr-avatar-img" alt="" onerror="this.onerror=null;fallbackAvatar(this)" />'
                else:
                    rc = 'av-a' if other.role == 'admin' else ('av-m' if other.role == 'management' else 'av-u')
                    avatar = f'<div class="av {rc}">{other.username[0].upper()}</div>'
                show_members = 'display:none'
            except CustomUser.DoesNotExist:
                title = active_channel.name
                subtitle = ''
                avatar = '<i class="ti ti-message" style="font-size:22px;color:var(--accent)"></i>'
                show_members = 'display:none'
        else:
            title = active_channel.name
            members = active_channel.members.all()
            subtitle = _member_subtitle(members, user)
            if active_channel.profile_pic_url:
                avatar = f'<img src="{active_channel.profile_pic_url}" class="hdr-avatar-img" alt="" onerror="this.onerror=null;fallbackAvatar(this)" />'
            else:
                rc = 'av-a' if slug == 'admin' else ('av-m' if slug == 'management' else 'av-u')
                avatar = f'<div class="av {rc}" style="width:40px;height:40px;font-size:16px;border-radius:50%">{active_channel.name[0].upper()}</div>'
            show_members = ''

        member_count = active_channel.members.count()
        oob = ''
        oob += f'<div class="ch-title" id="chatTitle" hx-swap-oob="true">{escape(title)}</div>'
        oob += f'<div class="ch-subtitle" id="chatSub" hx-swap-oob="true">{escape(subtitle)}</div>'
        oob += f'<div id="hdrAvatar" hx-swap-oob="outerHTML" class="hdr-avatar" onclick="onHdrAvatarClick()" style="cursor:pointer">{avatar}</div>'
        oob += f'<span id="memberCountWrap" hx-swap-oob="outerHTML" style="font-size:13px;color:var(--text-muted);white-space:nowrap;flex-shrink:0;{show_members}"><span id="memberCount" style="font-weight:600;color:var(--text-secondary)">{member_count}</span> members</span>'
        oob += f'<input type="hidden" id="chatDesc" hx-swap-oob="outerHTML" value="{escape(active_channel.description or "")}" />'
        oob += f'<textarea class="msg-ta" id="msgInput" hx-swap-oob="outerHTML" rows="1" placeholder="Message #{escape(active_channel.name)}..." oninput="onType(this)" onkeydown="handleMsgKeydown(event,this)"></textarea>'
        oob += f'<title hx-swap-oob="innerHTML">{escape(title)} — HanuAI Connect</title>'
        oob += f'<input type="hidden" id="scrollToMsg" hx-swap-oob="outerHTML" value="{escape(request.GET.get("msg_id", ""))}" />'

        return HttpResponse(msgs_html + oob)

    active = _active_channels_qs(user).annotate(member_count=Count('members'))
    archived = _archived_channels_qs(user).annotate(member_count=Count('members'))
    deleted = _deleted_channels_qs(user).annotate(member_count=Count('members'))
    all_users = CustomUser.objects.all() if user.role in ('admin', 'management') else CustomUser.objects.exclude(role='admin')

    messages_list = ChatMessage.objects.filter(
        channel=active_channel,
        is_deleted_for_everyone=False
    ).exclude(deleted_for=request.user).select_related('sender', 'reply_to__sender')[:25]

    channel_members = active_channel.members.all()

    unread_counts = Notification.objects.filter(
        user=user, channel__in=active, is_read=False
    ).values('channel__slug').annotate(count=Count('id'))
    unread_map = {item['channel__slug']: item['count'] for item in unread_counts}

    def _ch_json(qs):
        return json.dumps([dict({
            'name': c.name, 'slug': c.slug, 'description': c.description or '',
            'profile_pic_url': c.profile_pic_url, 'member_count': c.member_count,
            'member_names': _member_subtitle(c.members.all(), request.user),
            'member_ids': [m.id for m in c.members.all()],
            'is_archived': c.is_archived, 'is_deleted': c.is_deleted,
            'deleted_at': c.deleted_at.isoformat() if c.deleted_at else None,
        }, **_latest_message_data(c, request.user)) for c in qs])

    context = {
        'channels': active,
        'all_users_json': json.dumps([{'id': u.id, 'username': u.username, 'role': u.role, 'initial': u.username[0].upper(), 'email': u.email or '', 'department': u.department or '', 'about': u.about or '', 'profile_pic_url': u.profile_pic_url(), 'last_seen': u.last_seen.isoformat() if u.last_seen else None, 'is_active': u.is_active} for u in all_users]),
        'channels_json': _ch_json(active),
        'archived_channels_json': _ch_json(archived),
        'deleted_channels_json': _ch_json(deleted),
        'active_channel': active_channel,
        'messages': messages_list,
        'channel_members': channel_members,
        'member_subtitle': _member_subtitle(channel_members, request.user),
        'unread_map_json': json.dumps(unread_map),
        'dm_preview_json': json.dumps(_dm_preview_data(request.user)),
        'MEDIA_URL': settings.MEDIA_URL,
        'channel_member_ids_json': json.dumps([m.id for m in channel_members]),
        'unread_mentions': Notification.objects.filter(user=user, type='mention', is_read=False).count(),
        'scroll_to_msg': request.GET.get('msg_id', ''),
    }

    return render(request, 'channel_detail.html', context)


@login_required
@require_POST
def create_channel(request):
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    if name:
        channel = TeamChannel.objects.create(
            name=name,
            slug=slugify(name),
            description=description
        )
        mgmt_users = CustomUser.objects.filter(role='management')
        channel.members.add(*mgmt_users)
        return JsonResponse({'success': True, 'slug': channel.slug, 'name': channel.name})
    return JsonResponse({'error': 'Name required'}, status=400)


@login_required
@require_POST
def edit_channel(request, slug):
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    channel = get_object_or_404(TeamChannel, slug=slug)
    if channel.slug in ['admin', 'management']:
        return JsonResponse({'error': 'Cannot edit protected channels'}, status=403)
    if channel.is_archived:
        return JsonResponse({'error': 'Cannot edit archived channel'}, status=403)

    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    if name:
        channel.name = name
        channel.slug = slugify(name)
        channel.description = description
        channel.save()
        return JsonResponse({'success': True, 'slug': channel.slug, 'name': channel.name})
    return JsonResponse({'error': 'Name required'}, status=400)


@login_required
@require_POST
def archive_channel(request, slug):
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    channel = get_object_or_404(TeamChannel, slug=slug)
    if channel.slug in ['admin', 'management']:
        return JsonResponse({'error': 'Cannot archive protected channels'}, status=403)
    if channel.is_deleted:
        return JsonResponse({'error': 'Channel is deleted'}, status=400)

    channel.is_archived = True
    channel.save()
    return JsonResponse({'success': True, 'slug': channel.slug})


@login_required
@require_POST
def unarchive_channel(request, slug):
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    channel = get_object_or_404(TeamChannel, slug=slug)
    if not channel.is_archived:
        return JsonResponse({'error': 'Channel is not archived'}, status=400)

    channel.is_archived = False
    channel.save()
    return JsonResponse({'success': True, 'slug': channel.slug})


@login_required
@require_POST
def delete_channel(request, slug):
    """Move channel to Recently Deleted (soft delete) — admin only."""
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    channel = get_object_or_404(TeamChannel, slug=slug)
    if channel.slug in ['admin', 'management']:
        return JsonResponse({'error': 'Cannot delete protected channels'}, status=403)
    if channel.is_deleted:
        return JsonResponse({'error': 'Already deleted'}, status=400)

    from django.utils import timezone
    channel.is_deleted = True
    channel.deleted_at = timezone.now()
    channel.save()
    return JsonResponse({'success': True, 'slug': channel.slug})


@login_required
@require_POST
def restore_channel(request, slug):
    """Restore a recently deleted channel — admin only."""
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    channel = get_object_or_404(TeamChannel, slug=slug)
    if not channel.is_deleted:
        return JsonResponse({'error': 'Channel is not deleted'}, status=400)

    channel.is_deleted = False
    channel.deleted_at = None
    channel.save()
    return JsonResponse({'success': True, 'slug': channel.slug})


@login_required
@require_POST
def permanent_delete_channel(request, slug):
    """Permanently delete a recently deleted channel — admin only."""
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    channel = get_object_or_404(TeamChannel, slug=slug)
    if not channel.is_deleted:
        return JsonResponse({'error': 'Channel must be in Recently Deleted first'}, status=400)

    channel.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def manage_channel_users(request, slug):
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    channel = get_object_or_404(TeamChannel, slug=slug)
    if channel.is_archived:
        return JsonResponse({'error': 'Cannot modify members of archived channel'}, status=403)
    data = json.loads(request.body)
    user_ids = data.get('user_ids', [])
    action = data.get('action', 'set')

    mgmt_ids = set(CustomUser.objects.filter(role='management').values_list('id', flat=True))
    if action == 'add':
        users = CustomUser.objects.filter(id__in=user_ids)
        channel.members.add(*users)
    elif action == 'remove':
        filtered_ids = [uid for uid in user_ids if uid not in mgmt_ids]
        if filtered_ids:
            users = CustomUser.objects.filter(id__in=filtered_ids)
            channel.members.remove(*users)
    else:
        all_ids = set(user_ids) | mgmt_ids
        channel.members.set(list(all_ids))

    return JsonResponse({
        'success': True,
        'members': [
            {'id': u.id, 'username': u.username, 'role': u.role}
            for u in channel.members.all()
        ]
    })


@login_required
def channel_users_api(request, slug):
    channel = get_object_or_404(TeamChannel, slug=slug)
    members = channel.members.all()
    data = [
        {
            'id': u.id,
            'username': u.username,
            'role': u.role,
            'initial': u.username[0].upper()
        }
        for u in members
    ]
    return JsonResponse({'members': data})


@login_required
@require_POST
def broadcast_message(request):
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.user.role not in ('admin', 'management'):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    data = json.loads(request.body)
    message_text = data.get('message', '').strip()
    target = data.get('target', 'all')
    channel_slugs = data.get('channels', [])
    user_ids = data.get('user_ids', [])

    if not message_text:
        return JsonResponse({'error': 'Message required'}, status=400)

    channel_layer = get_channel_layer()
    created_messages = []

    if target == 'all':
        channels = TeamChannel.objects.filter(is_archived=False, is_deleted=False)
        for ch in channels:
            msg = ChatMessage.objects.create(
                channel=ch, sender=request.user,
                message=message_text, is_delivered=True,
                is_broadcast=True, broadcast_type='all'
            )
            created_messages.append({
                'id': msg.id, 'channel': ch.slug, 'channel_name': ch.name
            })
            async_to_sync(channel_layer.group_send)(
                f'chat_{ch.id}',
                {
                    'type': 'chat_message',
                    'message': message_text,
                    'sender': request.user.username,
                    'sender_id': request.user.id,
                    'message_id': msg.id,
                    'is_broadcast': True,
                }
            )
            member_ids = list(ch.members.exclude(id=request.user.id).values_list('id', flat=True))
            Notification.objects.bulk_create([
                Notification(
                    user_id=mid, sender=request.user, type='broadcast', priority=1,
                    title=f"Broadcast from {request.user.username}",
                    body=message_text[:200], channel=ch, message=msg
                )
                for mid in member_ids
            ], ignore_conflicts=True)
            for mid in member_ids:
                async_to_sync(channel_layer.group_send)(
                    f'user_notifications_{mid}',
                    {
                        'type': 'notification_event',
                        'ntype': 'broadcast',
                        'priority': 1,
                        'title': f"Broadcast from {request.user.username}",
                        'body': message_text[:200],
                        'channel': ch.name,
                        'channel_slug': ch.slug,
                        'sender': request.user.username,
                        'sender_id': request.user.id,
                        'message_id': msg.id,
                    }
                )
    elif target == 'selected' and channel_slugs:
        channels = TeamChannel.objects.filter(slug__in=channel_slugs)
        for ch in channels:
            msg = ChatMessage.objects.create(
                channel=ch, sender=request.user,
                message=message_text, is_delivered=True,
                is_broadcast=True, broadcast_type='selected',
                broadcast_channels=','.join(channel_slugs)
            )
            created_messages.append({
                'id': msg.id, 'channel': ch.slug, 'channel_name': ch.name
            })
            async_to_sync(channel_layer.group_send)(
                f'chat_{ch.id}',
                {
                    'type': 'chat_message',
                    'message': message_text,
                    'sender': request.user.username,
                    'sender_id': request.user.id,
                    'message_id': msg.id,
                    'is_broadcast': True,
                }
            )
            member_ids = list(ch.members.exclude(id=request.user.id).values_list('id', flat=True))
            Notification.objects.bulk_create([
                Notification(
                    user_id=mid, sender=request.user, type='broadcast', priority=1,
                    title=f"Broadcast from {request.user.username}",
                    body=message_text[:200], channel=ch, message=msg
                )
                for mid in member_ids
            ], ignore_conflicts=True)
            for mid in member_ids:
                async_to_sync(channel_layer.group_send)(
                    f'user_notifications_{mid}',
                    {
                        'type': 'notification_event',
                        'ntype': 'broadcast',
                        'priority': 1,
                        'title': f"Broadcast from {request.user.username}",
                        'body': message_text[:200],
                        'channel': ch.name,
                        'channel_slug': ch.slug,
                        'sender': request.user.username,
                        'sender_id': request.user.id,
                        'message_id': msg.id,
                    }
                )
    elif target == 'user' and user_ids:
        for uid in user_ids:
            user_channel_slug = f'dm-{min(request.user.id, uid)}-{max(request.user.id, uid)}'
            ch, _ = TeamChannel.objects.get_or_create(
                slug=user_channel_slug,
                defaults={'name': f'DM-{min(request.user.id, uid)}-{max(request.user.id, uid)}'}
            )
            msg = ChatMessage.objects.create(
                channel=ch, sender=request.user,
                message=message_text, is_delivered=True,
                is_broadcast=True, broadcast_type='user'
            )
            ch.members.add(request.user.id, uid)
            created_messages.append({
                'id': msg.id, 'channel': ch.slug, 'channel_name': ch.name
            })
            async_to_sync(channel_layer.group_send)(
                f'chat_{ch.id}',
                {
                    'type': 'chat_message',
                    'message': message_text,
                    'sender': request.user.username,
                    'sender_id': request.user.id,
                    'message_id': msg.id,
                }
            )
            if uid != request.user.id:
                Notification.objects.create(
                    user_id=uid, sender=request.user, type='broadcast', priority=1,
                    title=f"Broadcast from {request.user.username}",
                    body=message_text[:200], channel=ch, message=msg
                )
                async_to_sync(channel_layer.group_send)(
                    f'user_notifications_{uid}',
                    {
                        'type': 'notification_event',
                        'ntype': 'broadcast',
                        'priority': 1,
                        'title': f"Broadcast from {request.user.username}",
                        'body': message_text[:200],
                        'channel': ch.name,
                        'channel_slug': ch.slug,
                        'sender': request.user.username,
                        'sender_id': request.user.id,
                        'message_id': msg.id,
                    }
                )

    return JsonResponse({'success': True, 'messages': created_messages})


@login_required
def message_history_api(request):
    user = request.user
    channel_slug = request.GET.get('channel')
    search = request.GET.get('search', '')
    days = request.GET.get('days', '')

    msgs = ChatMessage.objects.filter(
        is_deleted_for_everyone=False
    ).exclude(deleted_for=user).select_related('sender', 'channel', 'reply_to__sender')

    if user.role == 'admin':
        pass
    elif user.role == 'management':
        msgs = msgs.exclude(channel__slug='admin')
    else:
        msgs = msgs.filter(channel__in=user.team_channels.all())

    if channel_slug and channel_slug != 'all':
        msgs = msgs.filter(channel__slug=channel_slug)
    if search:
        msgs = msgs.filter(message__icontains=search)
    if days:
        from django.utils import timezone
        from datetime import timedelta
        try:
            msgs = msgs.filter(created_at__gte=timezone.now() - timedelta(days=int(days)))
        except ValueError:
            pass

    msgs = msgs.order_by('-created_at')[:100]

    data = [
        {
            'id': m.id,
            'message': m.message,
            'sender': m.sender.username,
            'sender_role': m.sender.role,
            'channel': m.channel.name,
            'channel_slug': m.channel.slug,
            'created_at': m.created_at.isoformat(),
            'is_edited': m.is_edited,
        }
        for m in msgs
    ]
    return JsonResponse({'messages': data})


@login_required
def notifications_api(request):
    user = request.user
    notifs = Notification.objects.filter(user=user).select_related('channel', 'message__sender', 'sender')[:50]
    unread_count = Notification.objects.filter(user=user, is_read=False).count()
    unread_mentions = Notification.objects.filter(user=user, type='mention', is_read=False).count()
    data = [
        {
            'id': n.id,
            'type': n.type,
            'priority': n.priority,
            'title': n.title,
            'body': n.body,
            'channel_slug': n.channel.slug if n.channel else None,
            'channel_name': n.channel.name if n.channel else None,
            'sender_username': n.sender.username if n.sender else (n.message.sender.username if n.message and n.message.sender else None),
            'sender_id': n.sender.id if n.sender else (n.message.sender.id if n.message and n.message.sender else None),
            'message_id': n.message.id if n.message else None,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat(),
        }
        for n in notifs
    ]
    return JsonResponse({'notifications': data, 'unread_count': unread_count, 'unread_mentions': unread_mentions})


@login_required
@require_POST
def mark_notifications_read(request):
    data = json.loads(request.body)
    nid = data.get('notification_id')
    if nid:
        Notification.objects.filter(id=nid, user=request.user).update(is_read=True)
    else:
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'success': True})


@login_required
@require_POST
def clear_notifications(request):
    Notification.objects.filter(user=request.user).delete()
    return JsonResponse({'success': True})


@login_required
def delete_for_me(request, message_id):
    if not request.user.is_active:
        return redirect('dashboard_home')
    message = get_object_or_404(ChatMessage, id=message_id)
    message.deleted_for.add(request.user)
    return redirect('channel_detail', slug=message.channel.slug)


@login_required
def delete_for_everyone(request, message_id):
    if not request.user.is_active:
        return redirect('dashboard_home')
    message = get_object_or_404(ChatMessage, id=message_id)
    if message.sender == request.user or request.user.role == 'admin':
        message.is_deleted_for_everyone = True
        message.message = "This message was deleted"
        message.file = None
        message.image = None
        message.save()
    return redirect('channel_detail', slug=message.channel.slug)


@login_required
@require_POST
def edit_message(request, message_id):
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    message = get_object_or_404(ChatMessage, id=message_id)
    if message.sender != request.user:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    if message.is_deleted_for_everyone:
        return JsonResponse({'error': 'Message deleted'}, status=400)

    data = json.loads(request.body)
    new_message = data.get('message', '').strip()
    if new_message:
        message.message = new_message
        message.is_edited = True
        message.save()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Message required'}, status=400)


@login_required
@require_POST
def upload_file(request):
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)

    channel_slug = request.POST.get('channel_slug', '').strip()
    message_text = request.POST.get('message', '').strip()
    uploaded_file = request.FILES.get('file')

    if not channel_slug or not uploaded_file:
        return JsonResponse({'error': 'Channel and file required'}, status=400)

    channel = get_object_or_404(TeamChannel, slug=channel_slug)
    user = request.user

    if channel.is_archived:
        return JsonResponse({'error': 'Cannot upload files to archived channel'}, status=403)
    if user.role == 'employee' and not channel.members.filter(id=user.id).exists():
        return JsonResponse({'error': 'Not a member of this channel'}, status=403)

    msg = ChatMessage.objects.create(
        channel=channel, sender=user,
        message=message_text or '',
        is_delivered=True
    )

    ext = os.path.splitext(uploaded_file.name)[1].lower()
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    if ext in image_exts:
        msg.image = uploaded_file
    else:
        msg.file = uploaded_file
    msg.save()

    channel_layer = get_channel_layer()
    file_url = msg.file.url if msg.file else msg.image.url
    async_to_sync(channel_layer.group_send)(
        f'chat_{channel.id}',
        {
            'type': 'chat_message',
            'message': message_text or '',
            'sender': user.username,
            'sender_id': user.id,
            'message_id': msg.id,
            'file_url': file_url,
            'file_name': uploaded_file.name,
            'is_image': ext in image_exts,
        }
    )

    if channel.is_archived:
        return JsonResponse({'error': 'Archived channels cannot receive new messages'}, status=403)

    member_ids = list(channel.members.exclude(id=user.id).values_list('id', flat=True))
    Notification.objects.bulk_create([
        Notification(
            user_id=mid, sender=user, type='message', priority=4,
            title=f"File from {user.username}",
            body=message_text[:200] if message_text else uploaded_file.name,
            channel=channel, message=msg
        )
        for mid in member_ids
    ], ignore_conflicts=True)

    return JsonResponse({
        'success': True,
        'message_id': msg.id,
        'file_url': file_url,
        'file_name': uploaded_file.name,
        'is_image': ext in image_exts,
    })


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def update_profile(request):
    if not request.user.is_active:
        return JsonResponse({'error': 'Account deactivated'}, status=403)
    if request.content_type == 'application/json':
        data = json.loads(request.body)
        user_id = data.get('user_id')
        if user_id and request.user.role == 'admin':
            user = get_object_or_404(CustomUser, id=user_id)
        else:
            user = request.user
        email = data.get('email', '').strip()
        department = data.get('department', '').strip()
        about = data.get('about', '').strip()
        if email:
            user.email = email
        user.department = department if department else None
        user.about = about if about else None
        if request.user.role == 'admin' and data.get('role'):
            new_role = data.get('role')
            if new_role in ['admin', 'management', 'employee']:
                user.role = new_role
        user.save()
        return JsonResponse({'success': True, 'email': user.email or '', 'department': user.department or '', 'about': user.about or '', 'role': user.role})
    elif request.FILES.get('profile_pic'):
        user_id = request.POST.get('user_id')
        if user_id and request.user.role == 'admin':
            user = get_object_or_404(CustomUser, id=user_id)
        else:
            user = request.user
        user.profile_pic = request.FILES['profile_pic']
        user.save()
        return JsonResponse({'success': True, 'profile_pic_url': user.profile_pic_url()})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@require_POST
def upload_channel_pic(request, slug):
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    channel = get_object_or_404(TeamChannel, slug=slug)
    if channel.is_archived:
        return JsonResponse({'error': 'Cannot edit archived channel'}, status=403)
    if request.FILES.get('profile_pic'):
        channel.profile_pic = request.FILES['profile_pic']
        channel.save()
        return JsonResponse({'success': True, 'profile_pic_url': channel.profile_pic_url})
    return JsonResponse({'error': 'No file'}, status=400)


@login_required
def channel_shared_content(request, slug):
    channel = get_object_or_404(TeamChannel, slug=slug)
    messages_list = ChatMessage.objects.filter(channel=channel).order_by('-created_at').only('image', 'file', 'message', 'created_at')[:200]

    media, docs, links = [], [], []

    for msg in messages_list:
        if msg.image:
            media.append({
                'id': msg.id,
                'image_url': msg.image.url,
                'created_at': msg.created_at.isoformat(),
            })
        if msg.file:
            ext = os.path.splitext(msg.file.name)[1].lower()
            docs.append({
                'id': msg.id,
                'file_url': msg.file.url,
                'file_name': os.path.basename(msg.file.name),
                'file_ext': ext,
                'created_at': msg.created_at.isoformat(),
            })
        if msg.message:
            urls = re.findall(r'https?://[^\s]+', msg.message)
            for url in urls:
                links.append({
                    'id': msg.id,
                    'url': url,
                    'created_at': msg.created_at.isoformat(),
                })

    return JsonResponse({'media': media, 'docs': docs, 'links': links})


@login_required
@require_POST
def send_announcement(request):
    if request.user.role not in ('admin', 'management'):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    data = json.loads(request.body)
    title = data.get('title', '').strip()
    message = data.get('message', '').strip()
    priority = data.get('priority', 'medium')
    target = data.get('target', 'channel')
    channel_slug = data.get('channel_slug', '')
    if not title or not message:
        return JsonResponse({'error': 'Title and message required'}, status=400)
    priority = priority.lower()
    if priority not in ('low', 'medium', 'high'):
        priority = 'medium'
    ann_data = json.dumps({'title': title, 'msg': message, 'priority': priority, 'sender': request.user.username}, ensure_ascii=False)
    channel_layer = get_channel_layer()
    if target == 'channel' and channel_slug:
        try:
            ch = TeamChannel.objects.get(slug=channel_slug)
        except TeamChannel.DoesNotExist:
            return JsonResponse({'error': 'Channel not found'}, status=404)
        msg = ChatMessage.objects.create(channel=ch, sender=request.user, message='[ANN]' + ann_data, is_delivered=True)
        async_to_sync(channel_layer.group_send)(
            f'chat_{ch.id}',
            {
                'type': 'chat_message',
                'message': '[ANN]' + ann_data,
                'sender': request.user.username,
                'sender_id': request.user.id,
                'message_id': msg.id,
                'is_broadcast': False,
            }
        )
        member_ids = list(ch.members.exclude(id=request.user.id).values_list('id', flat=True))
        Notification.objects.bulk_create([
            Notification(
                user_id=mid, sender=request.user, type='system', priority=2,
                title=f"📢 {title[:80]}",
                body=message[:200], channel=ch, message=msg
            )
            for mid in member_ids
        ], ignore_conflicts=True)
        return JsonResponse({'success': True, 'message_id': msg.id, 'channel': ch.slug})
    elif target in ('all', 'selected'):
        channels = TeamChannel.objects.filter(slug__in=data.get('channels', [])) if target == 'selected' and data.get('channels') else TeamChannel.objects.all()
        created = []
        for ch in channels:
            msg = ChatMessage.objects.create(channel=ch, sender=request.user, message='[ANN]' + ann_data, is_delivered=True)
            created.append({'id': msg.id, 'channel': ch.slug})
            async_to_sync(channel_layer.group_send)(
                f'chat_{ch.id}',
                {
                    'type': 'chat_message',
                    'message': '[ANN]' + ann_data,
                    'sender': request.user.username,
                    'sender_id': request.user.id,
                    'message_id': msg.id,
                    'is_broadcast': True,
                }
            )
            member_ids = list(ch.members.exclude(id=request.user.id).values_list('id', flat=True))
            Notification.objects.bulk_create([
                Notification(
                    user_id=mid, sender=request.user, type='system', priority=2,
                    title=f"📢 {title[:80]}",
                    body=message[:200], channel=ch, message=msg
                )
                for mid in member_ids
            ], ignore_conflicts=True)
        return JsonResponse({'success': True, 'messages': created})
    return JsonResponse({'error': 'Invalid target'}, status=400)

