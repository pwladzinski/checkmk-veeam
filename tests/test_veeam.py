import contextlib
import importlib.util
import io
import json
import sys
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'veeam_native'
COLLECTOR = ROOT / 'libexec/agent_veeam_native'
CHECKS = ROOT / 'agent_based/veeam_native.py'

spec = importlib.util.spec_from_file_location('veeam_native_collector', str(COLLECTOR))
# importlib does not choose a Python loader for a shebang executable without .py
from importlib.machinery import SourceFileLoader
spec = importlib.util.spec_from_loader('veeam_native_collector', SourceFileLoader('veeam_native_collector', str(COLLECTOR)))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

m = types.ModuleType('cmk')
a = types.ModuleType('cmk.agent_based')
v = types.ModuleType('cmk.agent_based.v2')
class Dummy:
    def __init__(self, **kwargs): self.kwargs = kwargs
class Result:
    def __init__(self, state, summary=None, notice=None): self.state,self.summary,self.notice=state,summary,notice
class State:
    OK='OK';WARN='WARN';CRIT='CRIT';UNKNOWN='UNKNOWN'
class Metric:
    def __init__(self, name, value, **kwargs): self.name,self.value=name,value
for key,obj in {'AgentSection':Dummy,'CheckPlugin':Dummy,'Service':Dummy,'Result':Result,'State':State,'Metric':Metric}.items(): setattr(v,key,obj)
sys.modules['cmk']=m
sys.modules['cmk.agent_based']=a
sys.modules['cmk.agent_based.v2']=v
spec2=importlib.util.spec_from_file_location('veeam_native_checks',CHECKS)
checks=importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(checks)

J=[{'id':'vsphere-1','name':'Example VMware Backup','type':'VSphereBackup','status':'Inactive','lastResult':'Success'}]
REPOS=[{'name':'repo','capacityGB':100,'freeGB':45,'isOnline':True}]
now=datetime.now(timezone.utc)
def entry(dt_offset,name,job_id,kind,result='Success'):
    start=now+timedelta(minutes=dt_offset)
    return {'id':f'session-{name}-{dt_offset}', 'jobId':job_id, 'name':name,
            'platformName':'CustomPlatform', 'sessionType':kind, 'state':'Stopped',
            'creationTime':start.isoformat(), 'endTime':(start+timedelta(minutes=1)).isoformat(),
            'result':{'result':result,'message':result}, 'progressPercent':100}

S=[entry(-90,'Example Morpheus Backup','morpheus-1','PlatformBackupJob')]
KASTEN = [entry(-20*i-60, 'example-kasten-policy','kasten-job-abc','PlatformSnapshotJob',
                 'Failed' if i==0 else 'Success') for i in range(149)]
KASTEN.append(entry(-80, 'other-snapshot-policy', 'other-snap-1', 'PlatformSnapshotJob', 'Warning'))
KASTEN.append(entry(-100, 'no-id-policy', collector.EMPTY_ID, 'PlatformSnapshotJob', 'Success'))
KASTEN.append(entry(-70, 'kasten-io', 'kasten-pod-1', 'EndpointBackup', 'Success'))

class FakeClient:
    def __init__(self,opts): self.request_count=1; self.calls=[]
    def listing(self,path,filters=None):
        self.request_count+=1
        self.calls.append((path,filters))
        if path.endswith('/jobs/states'): return J
        if path.endswith('/sessions'):
            src=S+KASTEN
            if filters:
                src=[x for x in src if x.get('sessionType')==filters.get('typeFilter') and x.get('creationTime','')>=filters.get('createdAfterFilter','')]
            return src
        if path.endswith('/repositories/states'): return REPOS
        raise AssertionError('unexpected query '+path)
    def get(self,path): raise AssertionError('unexpected GET '+path)

class CollectorChecks(unittest.TestCase):
    def test_snapshot_grouping(self):
        backup,snaps,endpoints = collector.latest_sessions(KASTEN, 14)
        self.assertEqual(len(backup),0)
        self.assertEqual(len(snaps),3)
        self.assertEqual(len(endpoints),1)
        self.assertEqual(next(s for s in snaps if s['name']=='example-kasten-policy')['result']['result'],'Failed')

    def test_unified_and_results(self):
        previous=collector.Client
        collector.Client=FakeClient
        try:
            opts=SimpleNamespace(history_days=14,skip_snapshot_jobs=False,monitor_vm_sessions=False,
               monitor_backup_catalog=False,monitor_protected_objects=False,monitor_infrastructure=False,
               monitor_api_details=False,monitor_security=False,monitor_replicas=False)
            output=io.StringIO()
            with contextlib.redirect_stdout(output): collector.run(opts)
        finally: collector.Client=previous
        payload=output.getvalue()
        sections={}
        current=None
        for line in payload.splitlines():
            if line.startswith('<<<veeam_native_'):
                current=line.split(':')[0].removeprefix('<<<veeam_native_')
            elif current:
                sections[current]=json.loads(line);current=None
        self.assertIn('jobs',sections)
        self.assertIn('api',sections)
        self.assertNotIn('morpheus_vms',sections)
        jobs=sections['jobs']
        self.assertEqual(len([j for j in jobs if j['name']=='example-kasten-policy']),1)
        kasten=next(j for j in jobs if j['name']=='example-kasten-policy')
        self.assertEqual(kasten['type'],'KastenPolicy')
        self.assertEqual(kasten['lastResult'],'Failed')
        self.assertEqual(len([j for j in jobs if j.get('type') == 'CustomPlatformSnapshot']),2)
        self.assertNotIn('kasten-io',[j['name'] for j in jobs])
        self.assertEqual(sections['api']['counts']['custom_platform_snapshot_jobs'],3)
        self.assertEqual(sections['api']['request_count'],5) # OAuth + 4 collection requests
        self.assertEqual(list(checks.job_check(kasten['name'], {}, jobs))[0].state,'CRIT')

    def test_optional_toggle(self):
        previous=collector.Client
        collector.Client=FakeClient
        try:
            opts=SimpleNamespace(history_days=14,skip_snapshot_jobs=True,monitor_vm_sessions=False,
               monitor_backup_catalog=False,monitor_protected_objects=False,monitor_infrastructure=False,
               monitor_api_details=False,monitor_security=False,monitor_replicas=False)
            output=io.StringIO()
            with contextlib.redirect_stdout(output):collector.run(opts)
        finally:collector.Client=previous
        self.assertNotIn('example-kasten-policy',output.getvalue())
        self.assertIn('"custom_platform_snapshot_jobs":null',output.getvalue())


    def test_job_age_policies(self):
        self.assertIsNone(checks.job_age_thresholds({'age_policy':'off'}))
        self.assertEqual(checks.job_age_thresholds({'age_policy':'weekly'}), (192, 240))
        self.assertEqual(checks.job_age_thresholds({'age_policy':'daily'}), (30, 48))
        self.assertEqual(checks.job_age_thresholds({'age_warn_hours': 36, 'age_crit_hours': 72}), (36, 72))
        job={'id':'job1','name':'WeeklyJob','type':'VSphereBackup','status':'Stopped','lastResult':'Success',
             'lastRun':(datetime.now(timezone.utc)-timedelta(days=5)).isoformat()}
        # Without a declared cadence, an old but successful job is not a false CRIT.
        results=list(checks.job_check('WeeklyJob', {}, [job]))
        self.assertTrue(all(r.state=='OK' for r in results if isinstance(r,Result)))
        results=list(checks.job_check('WeeklyJob', {'age_policy':'weekly'}, [job]))
        self.assertTrue(all(r.state=='OK' for r in results if isinstance(r,Result)))
        results=list(checks.job_check('WeeklyJob', {'age_policy':'daily'}, [job]))
        self.assertTrue(any(r.state=='CRIT' for r in results if isinstance(r,Result)))
        job['lastResult']='Failed'
        results=list(checks.job_check('WeeklyJob', {'age_policy':'off'}, [job]))
        self.assertEqual(results[0].state,'CRIT')

    def test_duplicate_types_get_readable_suffix(self):
        jobs=[{'name':'example-workload','id':'abc-123','sessionType':'PlatformBackupJob'},
              {'name':'example-workload','id':'snapshot:example-workload','sessionType':'PlatformSnapshotJob'}]
        collector.disambiguate_duplicate_names(jobs)
        self.assertEqual(jobs[0]['name'],'example-workload [backup]')
        self.assertEqual(jobs[1]['name'],'example-workload [snapshot]')

if __name__=='__main__':unittest.main(verbosity=2)
