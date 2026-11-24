# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) 2026 Pawel Wladzinski
from cmk.server_side_calls.v1 import SpecialAgentConfig, SpecialAgentCommand, noop_parser

def commands(params, host_config):
    command=['--host',params['url'],'--username',params['username'], '--password',params['password'].unsafe(),
             '--api-version',params.get('api_version','1.3-rev2'),'--timeout',str(params.get('timeout',15)),
             '--budget',str(params.get('budget',180)),'--history-days',str(params.get('history_days',14))]
    if params.get('port') is not None:command.extend(['--port',str(params['port'])])
    if params.get('insecure'):command.append('--insecure')
    if params.get('skip_snapshot_jobs'):command.append('--skip-snapshot-jobs')
    if params.get('ca_file'):command.extend(['--ca-file',params['ca_file']])
    for key,flag in [('monitor_vm_sessions','--monitor-vm-sessions'),('monitor_backup_catalog','--monitor-backup-catalog'),
                     ('monitor_protected_objects','--monitor-protected-objects'),('monitor_infrastructure','--monitor-infrastructure'),
                     ('monitor_api_details','--monitor-api-details'),('monitor_security','--monitor-security'),
                     ('monitor_replicas','--monitor-replicas')]:
        if params.get(key):command.append(flag)
    yield SpecialAgentCommand(command_arguments=command)

special_agent_veeam_native=SpecialAgentConfig(name='veeam_native',parameter_parser=noop_parser,commands_function=commands)
