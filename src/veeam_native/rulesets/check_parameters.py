# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) 2026 Pawel Wladzinski
from cmk.rulesets.v1 import Title
from cmk.rulesets.v1.form_specs import Dictionary, DictElement, Integer, BooleanChoice, DefaultValue, SingleChoice, SingleChoiceElement, validators
from cmk.rulesets.v1.rule_specs import CheckParameters, HostAndItemCondition, Topic

def form():
    return Dictionary(elements={
        'age_policy': DictElement(parameter_form=SingleChoice(
            title=Title('Last backup age monitoring'),
            prefill=DefaultValue('off'),
            elements=[
                SingleChoiceElement(name='off', title=Title('Disabled (status and result only)')),
                SingleChoiceElement(name='daily', title=Title('Daily: WARN after 30 h, CRIT after 48 h')),
                SingleChoiceElement(name='weekly', title=Title('Weekly: WARN after 8 days, CRIT after 10 days')),
                SingleChoiceElement(name='monthly', title=Title('Monthly: WARN after 35 days, CRIT after 40 days')),
                SingleChoiceElement(name='custom', title=Title('Custom thresholds (below)')),
            ],
        )),
        'age_warn_hours': DictElement(parameter_form=Integer(
            title=Title('Custom backup age WARN (hours)'),
            prefill=DefaultValue(36), custom_validate=(validators.NumberInRange(min_value=1),),
        )),
        'age_crit_hours': DictElement(parameter_form=Integer(
            title=Title('Custom backup age CRIT (hours)'),
            prefill=DefaultValue(72), custom_validate=(validators.NumberInRange(min_value=1),),
        )),
        'disabled': DictElement(parameter_form=SingleChoice(
            title=Title('State for disabled jobs'), prefill=DefaultValue('warn'),
            elements=[
                SingleChoiceElement(name='warn', title=Title('WARN')),
                SingleChoiceElement(name='crit', title=Title('CRIT')),
                SingleChoiceElement(name='ok', title=Title('OK')),
            ],
        )),
        'no_result': DictElement(parameter_form=SingleChoice(
            title=Title('State when no execution result exists'), prefill=DefaultValue('warn'),
            elements=[
                SingleChoiceElement(name='warn', title=Title('WARN')),
                SingleChoiceElement(name='unknown', title=Title('UNKNOWN')),
                SingleChoiceElement(name='ok', title=Title('OK')),
            ],
        )),
        'age_disabled': DictElement(parameter_form=BooleanChoice(
            title=Title('Apply backup age thresholds also to inactive/disabled jobs')),
        ),
    })

rule_spec_veeam_native_jobs=CheckParameters(name='veeam_native_jobs',title=Title('Veeam Job Monitoring'),topic=Topic.APPLICATIONS,parameter_form=form,condition=HostAndItemCondition(item_title=Title('Backup job or VM name')))


def repository_form():
    return Dictionary(elements={
        'free_warn_percent': DictElement(parameter_form=Integer(title=Title('Free space WARN at or below (%)'),prefill=DefaultValue(20),custom_validate=(validators.NumberInRange(min_value=0,max_value=100),))),
        'free_crit_percent': DictElement(parameter_form=Integer(title=Title('Free space CRIT at or below (%)'),prefill=DefaultValue(10),custom_validate=(validators.NumberInRange(min_value=0,max_value=100),))),
    })

rule_spec_veeam_native_repositories=CheckParameters(name='veeam_native_repositories',title=Title('Veeam Repository space thresholds'),topic=Topic.APPLICATIONS,parameter_form=repository_form,condition=HostAndItemCondition(item_title=Title('Veeam repository name')))
