# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) 2026 Pawel Wladzinski
"""Veeam B&R REST job monitoring including CustomPlatform backup and snapshot policies."""
import json
import math
from datetime import datetime, timezone
from cmk.agent_based.v2 import AgentSection, CheckPlugin, Service, Result, State, Metric


def parse(table):
    try:
        return json.loads(''.join(row[0] for row in table if row))
    except (ValueError, TypeError):
        return None

for _name in ('api','jobs','morpheus_vms','backups','objects','repositories','proxies','managed_servers','scaleout','wan','server','license','config','security','replicas'):
    globals()['agent_section_veeam_native_'+_name] = AgentSection(name='veeam_native_'+_name, parse_function=parse)


def age(value):
    if not isinstance(value, str): return None
    try:
        timestamp = datetime.fromisoformat(value.replace('Z','+00:00'))
        if timestamp.tzinfo is None: return None
        return (datetime.now(timezone.utc)-timestamp).total_seconds()
    except ValueError: return None

def good_number(value):
    return isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value)

def state_result(value, success=('success','ok','healthy','normal','passed'), warning=('warning','warn','pending','unknown','none'), failure=('failed','failure','error','critical','unhealthy')):
    if value is None: return State.UNKNOWN
    value = str(value).strip().lower()
    if value in success: return State.OK
    if value in failure: return State.CRIT
    if value in warning: return State.WARN
    return State.UNKNOWN

def items(section):
    if not isinstance(section,list): return
    for o in section:
        if isinstance(o,dict):
            yield o

def single(section):
    if section is not None: yield Service()

def pick_name(record):
    return str(record.get('name') or record.get('id') or 'unknown')

def discover_names(section):
    seen = set()
    for row in items(section):
        name = pick_name(row)
        if name not in seen:
            seen.add(name)
            yield Service(item=name)

def find_item(section,item):
    return next((o for o in items(section) if pick_name(o)==item),None)

def check_api(section):
    if not isinstance(section,dict):
        yield Result(state=State.CRIT, summary='Invalid REST collector response'); return
    if not section.get('success'):
        yield Result(state=State.CRIT,summary='REST authentication or connection failed: '+str('; '.join(section.get('errors',[])))[:400]); return
    sources=section.get('sources',{})
    required=('jobs','sessions')
    critical=[key for key in required if key not in sources or not sources[key].get('ok')]
    restricted=[key for key, value in sources.items() if value.get('restricted')]
    optional_errors=[key for key, value in sources.items() if not value.get('ok') and key not in critical and key not in restricted]
    state=State.CRIT if critical else State.WARN if restricted or optional_errors else State.OK
    counts=section.get('counts',{})
    total = counts.get('jobs')
    custom_backups = counts.get('custom_platform_backup_jobs')
    snapshots = counts.get('custom_platform_snapshot_jobs')
    summary = 'Job monitoring: %s jobs; CustomPlatform backups: %s, snapshot policies: %s' % (
        total if total is not None else 'unavailable',
        custom_backups if custom_backups is not None else 'unavailable',
        snapshots if snapshots is not None else 'disabled/unavailable')
    if good_number(section.get('duration')):
        summary += '; %.1f s' % section['duration']
    if isinstance(section.get('request_count'), int):
        summary += '; %d API requests' % section['request_count']
    if critical or restricted or optional_errors:
        summary += '; %s required, %s restricted, %s other failures' % (len(critical), len(restricted), len(optional_errors))
    yield Result(state=state, summary=summary)
    if critical:
        yield Result(state=State.CRIT,notice='Required endpoint failed or missing: '+', '.join(critical))
    if restricted:
        yield Result(state=State.WARN,notice='Insufficient access (HTTP 403): '+', '.join(restricted))
    if optional_errors:
        yield Result(state=State.WARN,notice='Other endpoint errors: '+', '.join(optional_errors))
    for error in section.get('errors',[])[:8]:
        yield Result(state=State.WARN,notice=str(error)[:250])
    if good_number(section.get('duration')): yield Metric('veeam_api_duration',section['duration'])
    if good_number(section.get('request_count')): yield Metric('veeam_api_requests',section['request_count'])
    if isinstance(counts.get('jobs'),int): yield Metric('veeam_job_count',counts['jobs'])
    if isinstance(counts.get('custom_platform_backup_jobs'), int):
        yield Metric('veeam_custom_platform_backup_job_count', counts['custom_platform_backup_jobs'])
    if isinstance(counts.get('custom_platform_snapshot_jobs'), int):
        yield Metric('veeam_custom_platform_snapshot_job_count', counts['custom_platform_snapshot_jobs'])
    yield Result(state=State.OK,notice='Collector '+str(section.get('version','?')))

check_plugin_veeam_native_api=CheckPlugin(name='veeam_native_api',service_name='Veeam REST API',discovery_function=single,check_function=check_api)


JOB_AGE_PRESETS = {
    'daily': (30, 48),
    'weekly': (192, 240),
    'monthly': (840, 960),
}


def job_age_thresholds(params):
    """Return hours, or None when no execution cadence has been configured.

    Historical rules that explicitly saved age_warn_hours/age_crit_hours stay
    active, while fresh rules no longer assume every job runs daily.
    """
    policy = params.get('age_policy')
    if policy in JOB_AGE_PRESETS:
        return JOB_AGE_PRESETS[policy]
    if policy == 'off':
        return None
    if policy == 'custom' or (policy is None and 'age_warn_hours' in params and 'age_crit_hours' in params):
        warn, crit = params.get('age_warn_hours', 36), params.get('age_crit_hours', 72)
        if isinstance(warn, (int, float)) and isinstance(crit, (int, float)) and 0 < warn < crit:
            return warn, crit
    return None


def job_check(item, params, section):
    job = find_item(section, item)
    if job is None:
        yield Result(state=State.UNKNOWN, summary='Job not present in current API data')
        return
    session_based = job.get('source') == 'session'
    status = str(job.get('status') or 'Unknown')
    running = status.lower() in ('working', 'running', 'starting')
    result = job.get('lastResult')
    if running:
        state, label = State.OK, 'Job running'
    elif result is None or str(result).strip().lower() in ('none', 'unknown', ''):
        status_if_missing = params.get('no_result', 'warn')
        state = {'warn': State.WARN, 'unknown': State.UNKNOWN, 'ok': State.OK}.get(status_if_missing, State.WARN)
        label = 'No recorded execution result'
    else:
        state = state_result(result)
        label = 'Last result: ' + str(result)
    if not session_based and status.lower() == 'disabled':
        disabled = params.get('disabled', 'warn')
        if disabled == 'crit':
            state = State.CRIT
        elif disabled == 'warn' and state != State.CRIT:
            state = State.WARN
        elif disabled == 'ok' and state != State.CRIT:
            state = State.OK
    yield Result(state=state, summary='%s; state: %s; type: %s' % (label, status, job.get('type', '?')))
    if job.get('repositoryName'):
        yield Result(state=State.OK, notice='Repository: ' + str(job['repositoryName']))
    if job.get('message') and state != State.OK:
        yield Result(state=state, notice=str(job['message'])[:300])
    last_time = job.get('endTime') or job.get('lastRun')
    if last_time:
        elapsed = age(last_time)
        if elapsed is None:
            yield Result(state=State.UNKNOWN, notice='Execution timestamp is invalid or lacks timezone')
        elif elapsed < -300:
            yield Result(state=State.UNKNOWN, summary='Execution timestamp is in the future')
        else:
            hours = max(0, elapsed) / 3600
            source = 'Last completion' if job.get('endTime') else 'Last start'
            yield Result(state=State.OK, notice='%s: %.1f h ago' % (source, hours))
            thresholds = job_age_thresholds(params)
            check_age = not running and (status.lower() not in ('disabled', 'inactive') or params.get('age_disabled', False))
            if thresholds is not None and check_age:
                warn, crit = thresholds
                severity = State.CRIT if hours >= crit else State.WARN if hours >= warn else State.OK
                yield Result(state=severity, summary='%s: %.1f h ago (WARN %sh, CRIT %sh)' % (source, hours, warn, crit))
                yield Metric('veeam_last_run_age', max(0, elapsed), levels=(warn * 3600, crit * 3600))
            else:
                yield Metric('veeam_last_run_age', max(0, elapsed))
    elif session_based and not running:
        yield Result(state=State.WARN, summary='Last execution timestamp missing')
    if good_number(job.get('progressPercent')):
        yield Metric('veeam_job_progress', job['progressPercent'], boundaries=(0, 100))
    if job.get('endTime') and job.get('lastRun'):
        start = age(job['lastRun'])
        end = age(job['endTime'])
        if start is not None and end is not None and 0 <= start - end < 86400 * 7:
            yield Metric('veeam_job_duration', start - end)

check_plugin_veeam_native_jobs=CheckPlugin(name='veeam_native_jobs',service_name='Veeam Job %s',discovery_function=discover_names,check_function=job_check,check_ruleset_name='veeam_native_jobs',check_default_parameters={'age_policy':'off','disabled':'warn','no_result':'warn','age_disabled':False})


def vm_check(item,params,section):
    row=find_item(section,item)
    if row is None:
        yield Result(state=State.UNKNOWN,summary='Object execution not present in selected history window'); return
    result=row.get('result') if isinstance(row.get('result'),dict) else {}
    result_value=result.get('result')
    running=str(row.get('state','')).lower() in ('working','running')
    severity=State.OK if running else state_result(result_value)
    yield Result(state=severity,summary='%s; %s' % (row.get('state','?'),result_value or 'no result'))
    if result.get('message') and severity!=State.OK: yield Result(state=severity,notice=str(result['message'])[:300])
    elapsed=age(row.get('creationTime'))
    if elapsed is not None and elapsed >= -300:
        warn=params.get('age_warn_hours',36);crit=params.get('age_crit_hours',72)
        hours=max(0,elapsed)/3600
        if not running:
            yield Result(state=State.CRIT if hours>=crit else State.WARN if hours>=warn else State.OK,summary='Last object backup %.1f h ago' % hours)
        yield Metric('veeam_last_run_age',max(0,elapsed),levels=(warn*3600,crit*3600))
    if good_number(row.get('progressPercent')): yield Metric('veeam_job_progress',row['progressPercent'],boundaries=(0,100))

# CustomPlatform EndpointBackup sessions are optional: not necessarily VM or Morpheus.
def vm_name(record):
    return str(record.get('name') or record.get('jobId') or record.get('id') or 'unknown')

def discover_vm(section):
    seen=set()
    for record in items(section):
        name=vm_name(record)
        if name not in seen:
            seen.add(name)
            yield Service(item=name)

check_plugin_veeam_native_morpheus_vms=CheckPlugin(name='veeam_native_morpheus_vms',service_name='Veeam Custom Object %s',discovery_function=discover_vm,check_function=vm_check,check_ruleset_name='veeam_native_jobs',check_default_parameters={'age_warn_hours':36,'age_crit_hours':72,'disabled':'warn','age_disabled':False})


def inventory_check(item,section,kind='inventory'):
    record=find_item(section,item)
    if record is None:
        yield Result(state=State.UNKNOWN,summary='Resource missing from API response');return
    status=next((record.get(key) for key in ('status','state','healthStatus','health','result') if record.get(key) is not None),None)
    if isinstance(status,dict): status=status.get('result')
    if status is None:
        if kind == 'backups':
            yield Result(state=State.UNKNOWN,summary='Backup listed in REST inventory; last execution and restore-point health not verified')
        else:
            yield Result(state=State.OK,summary='Present in REST inventory (health not supplied)')
    else:
        yield Result(state=state_result(status,success=('success','ok','healthy','normal','ready','available','online','enabled','working','idle'),warning=('warning','warn','unknown','maintenance','disabled','inactive','notconfigured'),failure=('failed','failure','error','critical','unhealthy','offline','unavailable')),summary='Status: '+str(status))
    for field in ('type','repositoryName','platformName','hostName','description'):
        if record.get(field): yield Result(state=State.OK,notice=field+': '+str(record[field])[:160])
    for field in ('capacityBytes','freeSpaceBytes','usedSpaceBytes','totalSpace','freeSpace','capacity','free'):
        if good_number(record.get(field)):
            yield Metric('veeam_'+''.join(c.lower() if c.islower() else '_'+c.lower() for c in field).lstrip('_'),record[field])


def check_repo(item,params,section):
    record=find_item(section,item)
    if record is None:
        yield Result(state=State.UNKNOWN,summary='Repository not present in API response')
        return
    online=record.get('isOnline')
    if isinstance(online,bool):
        yield Result(state=State.OK if online else State.CRIT,summary='Repository online' if online else 'Repository offline')
    elif record.get('status') is not None:
        yield Result(state=state_result(record['status'],success=('ok','online','available','ready','healthy'),failure=('error','offline','unavailable','failed'),warning=('warning','unknown','disabled','maintenance')),summary='Status: '+str(record['status']))
    else:
        yield Result(state=State.OK,summary='Repository listed (connection status not supplied)')
    if record.get('isOutOfDate') is True:
        yield Result(state=State.WARN,summary='Repository components out of date')
    # Veeam B&R REST uses capacityGB/freeGB. Other versions may return byte counters.
    for total, free, units in (('capacityGB','freeGB','GB'),('capacityBytes','freeSpaceBytes','bytes'),('totalSpace','freeSpace','bytes'),('capacity','free','bytes')):
        if good_number(record.get(total)) and good_number(record.get(free)) and record[total]>0:
            capacity=record[total]; available=record[free]
            if available < 0 or available > capacity:
                yield Result(state=State.UNKNOWN,notice='Inconsistent repository capacity/free space')
                break
            remaining=100*available/capacity
            warn = params.get('free_warn_percent', 20)
            crit = params.get('free_crit_percent', 10)
            state=State.CRIT if remaining <= crit else State.WARN if remaining <= warn else State.OK
            yield Result(state=state,summary='Free space: %.1f%% (%.1f / %.1f %s)' % (remaining,available,capacity,units))
            yield Metric('veeam_repository_free_percent',remaining)
            yield Metric('veeam_repository_free_gb',available if units=='GB' else available/(1024**3))
            yield Metric('veeam_repository_capacity_gb',capacity if units=='GB' else capacity/(1024**3))
            break

check_plugin_veeam_native_repositories=CheckPlugin(name='veeam_native_repositories',service_name='Veeam Repository %s',discovery_function=discover_names,check_function=check_repo,check_ruleset_name='veeam_native_repositories',check_default_parameters={'free_warn_percent': 20, 'free_crit_percent': 10})

def make_inventory_check(kind):
    def check(item, section):
        yield from inventory_check(item, section, kind=kind)
    return check

for _name,_label in [('proxies','Proxy'),('managed_servers','Managed Server'),('scaleout','Scale-out Repository'),('wan','WAN Accelerator'),('backups','Backup'),('objects','Protected Object'),('replicas','Replica')]:
    globals()['check_plugin_veeam_native_'+_name]=CheckPlugin(name='veeam_native_'+_name,service_name='Veeam '+_label+' %s',discovery_function=discover_names,check_function=make_inventory_check(_name))


def check_server(section):
    if not isinstance(section,dict):
        yield Result(state=State.UNKNOWN,summary='Missing server data');return
    for key in ('version','buildVersion','build','serverName','name'):
        if section.get(key):yield Result(state=State.OK,summary=key+': '+str(section[key])[:120])
    if not section:
        yield Result(state=State.UNKNOWN,summary='Empty server response')

check_plugin_veeam_native_server=CheckPlugin(name='veeam_native_server',service_name='Veeam Server',discovery_function=single,check_function=check_server)


def generic_check(section):
    if not isinstance(section,dict):
        yield Result(state=State.UNKNOWN,summary='Unexpected API payload'); return
    found=False
    for key in ('status','state','result','healthStatus'):
        if section.get(key) is not None:
            val=section[key]
            if isinstance(val,dict):val=val.get('result',val.get('status'))
            if val is not None:
                yield Result(state=state_result(val,success=('success','ok','healthy','normal','enabled','completed','valid'),warning=('warning','warn','unknown','disabled','pending'),failure=('failed','failure','error','critical','expired')),summary=key+': '+str(val));found=True
                break
    if not found:yield Result(state=State.OK,summary='REST data available (no health status)')
    for key in ('expirationDate','expires','expiryDate','lastRun','lastResult','nextRun','licenseType','edition','type','enabled'):
        if key in section:yield Result(state=State.OK,notice=key+': '+str(section[key])[:160])

for _name,_label in [('license','License'),('config','Configuration Backup')]:
    globals()['check_plugin_veeam_native_'+_name]=CheckPlugin(name='veeam_native_'+_name,service_name='Veeam '+_label,discovery_function=single,check_function=generic_check)


def security_discover(section):
    if section is not None:yield Service()

def security_check(section):
    rows=list(items(section))
    failing=[]
    for row in rows:
        status=str(row.get('status') or row.get('result') or '').lower()
        if status in ('failed','error','critical','noncompliant','violation','warning'):
            failing.append(str(row.get('name') or row.get('description') or row.get('id'))[:70])
    yield Result(state=State.WARN if failing else State.OK,summary='%s rules, %s findings' % (len(rows),len(failing)))
    if failing: yield Result(state=State.WARN,notice='Findings: '+', '.join(failing[:10]))
    yield Metric('veeam_security_findings',len(failing))

check_plugin_veeam_native_security=CheckPlugin(name='veeam_native_security',service_name='Veeam Security Analyzer',discovery_function=security_discover,check_function=security_check)
