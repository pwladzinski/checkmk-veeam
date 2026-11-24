# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) 2026 Pawel Wladzinski
from cmk.rulesets.v1 import Title, Label, Help
from urllib.parse import urlsplit
from cmk.rulesets.v1.form_specs import Dictionary, DictElement, String, Password, BooleanChoice, Integer, DefaultValue, migrate_to_password, validators
from cmk.rulesets.v1.rule_specs import SpecialAgent, Topic

def migrate_connection(value):
    """Move older https://server:port rules to the separate host/port fields."""
    if not isinstance(value, dict):
        return value
    updated = dict(value)
    old = updated.get('url')
    if isinstance(old, str) and old.startswith('https://'):
        try:
            parts = urlsplit(old)
            if parts.hostname and not parts.username and not parts.password and parts.path in ('', '/') and not parts.query and not parts.fragment:
                updated['url'] = ('[' + parts.hostname + ']') if ':' in parts.hostname else parts.hostname
                updated.setdefault('port', parts.port or 9419)
        except ValueError:
            pass
    # Legacy inventory flags are not carried forward to job-first monitoring.
    for old in ('collect_objects', 'collect_infrastructure', 'collect_security', 'collect_replicas'):
        updated.pop(old, None)
    updated.setdefault('port', 9419)
    return updated


def form():
    return Dictionary(migrate=migrate_connection, elements={
        'url':DictElement(required=True,parameter_form=String(title=Title('Server address (IP or FQDN)'),help_text=Help('Enter a hostname or IP address, without https:// or a port. Previously saved full URLs are also supported.'),custom_validate=(validators.LengthInRange(min_value=1),))),
        'port':DictElement(required=True,parameter_form=Integer(title=Title('Port'),prefill=DefaultValue(9419),custom_validate=(validators.NumberInRange(min_value=1,max_value=65535),))),
        'username':DictElement(required=True,parameter_form=String(title=Title('REST API username'))),
        'password':DictElement(required=True,parameter_form=Password(title=Title('REST API password'),migrate=migrate_to_password)),
        'api_version':DictElement(required=True,parameter_form=String(title=Title('Veeam REST API version'),prefill=DefaultValue('1.3-rev2'))),
        'insecure':DictElement(parameter_form=BooleanChoice(title=Title('Skip TLS certificate validation'),label=Label('Allow an untrusted certificate'))),
        'ca_file':DictElement(parameter_form=String(title=Title('Custom CA certificate file on site server'))),
        'history_days':DictElement(parameter_form=Integer(title=Title('Custom platform execution discovery window (days)'),prefill=DefaultValue(14),custom_validate=(validators.NumberInRange(min_value=1,max_value=90),))),
        'timeout':DictElement(parameter_form=Integer(title=Title('HTTP request timeout (seconds)'),prefill=DefaultValue(15),custom_validate=(validators.NumberInRange(min_value=1,max_value=120),))),
        'budget':DictElement(parameter_form=Integer(title=Title('Overall request budget (seconds)'),prefill=DefaultValue(180),custom_validate=(validators.NumberInRange(min_value=30,max_value=900),))),
        'skip_snapshot_jobs': DictElement(parameter_form=BooleanChoice(
            title=Title('Skip Kasten / CustomPlatform snapshot policies'),
            help_text=Help('Normally leave disabled. By default an additional filtered REST query monitors PlatformSnapshotJob policies (including Kasten, if exposed by VBR). This does not enumerate individual Kubernetes objects.'))),
        'monitor_vm_sessions': DictElement(parameter_form=BooleanChoice(title=Title('Per-object CustomPlatform checks (optional)'), help_text=Help('Adds filtered EndpointBackup sessions and individual checks for Morpheus VMs or other custom-platform objects, including Kasten. Disabled by default: monitor parent jobs/policies instead.'))),
        'monitor_backup_catalog': DictElement(parameter_form=BooleanChoice(title=Title('Backup inventory (optional)'), help_text=Help('Creates inventory-only Veeam Backup services; these are not verification of restore-point health. Normally leave disabled.'))),
        'monitor_protected_objects': DictElement(parameter_form=BooleanChoice(title=Title('Protected object inventory (optional)'), help_text=Help('Creates per-object inventory services. Normally leave disabled.'))),
        'monitor_infrastructure': DictElement(parameter_form=BooleanChoice(title=Title('Additional infrastructure (optional)'), help_text=Help('Additional API calls for proxies, managed servers, scale-out repositories and WAN accelerators.'))),
        'monitor_api_details': DictElement(parameter_form=BooleanChoice(title=Title('Server, license and configuration details (optional)'), help_text=Help('Some endpoints require elevated privileges and may return HTTP 403 for read-only accounts.'))),
        'monitor_security': DictElement(parameter_form=BooleanChoice(title=Title('Security analyzer (optional)'))),
        'monitor_replicas': DictElement(parameter_form=BooleanChoice(title=Title('Replica inventory (optional)'))),
    })

rule_spec_veeam_native=SpecialAgent(name='veeam_native',title=Title('Veeam B&R API'),topic=Topic.APPLICATIONS,parameter_form=form)
