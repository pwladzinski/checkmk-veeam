# Veeam B&R API for Checkmk — 1.0.0

Read-only Checkmk special agent for Veeam Backup & Replication REST API.

## Support

- Checkmk **2.4 and 2.5** (public v1/v2 plugin APIs; test with your exact patch level).
- Veeam B&R REST API at `https://HOST:9419`, API version configurable (`1.3-rev2` by default).
- Requires `requests` in the Python environment of the Checkmk site.
- Monitoring of VBR jobs returned by `/api/v1/jobs/states`, including VMware, Hyper-V, Backup Copy, and other job types exposed by VBR.
- CustomPlatform `PlatformBackupJob` execution sessions (e.g. HPE Morpheus VM Essentials backup jobs).
- CustomPlatform `PlatformSnapshotJob` sessions (including Kasten policies synchronized to VBR, when exposed there).
- Backup repositories: connectivity and free capacity (default WARN <=20%, CRIT <=10%).
- Optional inventory and per-object checks are **off by default**.

The plugin monitors **available REST data**. Unsupported workloads or restrictions such as `HTTP 400 - License restrictions apply` are reported as missing data, **not** success.

## Job status and age policy

`Veeam Job Monitoring` is a per-host/per-item Checkmk check-parameter rule. It supports:

| Age policy | WARN | CRIT |
|---|---:|---:|
| Disabled (default) | — | — |
| Daily | 30 hours | 48 hours |
| Weekly | 8 days | 10 days |
| Monthly | 35 days | 40 days |
| Custom | user-defined | user-defined |

A job's result `Failed` remains **CRIT** and `Warning` remains **WARN** regardless of the age setting. Running jobs are not treated as failed just because a previous result is absent. `Inactive` is not an error on its own. Disabled jobs and missing execution results have their own configurable severity.

**Why age monitoring is opt-in:** `/jobs/states` and CustomPlatform sessions do not consistently expose job schedules. A global 36/72-hour threshold produces false alarms for weekly/monthly jobs. Assign job-specific rules or groups by interval to detect missed scheduled executions. If you had previously stored explicit `age_warn_hours` / `age_crit_hours` without `age_policy`, the legacy values still apply.

For session-based jobs the last completion time is used where present; for jobs where only `lastRun` is supplied by VBR, the last start time is used and labelled as such.

## Installation

The package is available directly from this repository:

`https://raw.githubusercontent.com/pwladzinski/checkmk-veeam/main/releases/veeam_native-1.0.0.mkp`

Download and install as the Checkmk site user:

```bash
wget -O /tmp/veeam_native-1.0.0.mkp \
  https://raw.githubusercontent.com/pwladzinski/checkmk-veeam/main/releases/veeam_native-1.0.0.mkp
mkp add /tmp/veeam_native-1.0.0.mkp
# Disable any previously enabled veeam_native version, for example:
mkp disable veeam_native 1.0.6
mkp enable veeam_native 1.0.0
cmk -R
```

Then configure **Setup → Agents → Other integrations → Veeam B&R API** with address,
port (default 9419), username, password and TLS verification. Run service discovery on
the monitored Veeam host.

The default package is job-focused. Assign `Veeam Job Monitoring` check-parameter
rules to backup schedules (daily, weekly, monthly or custom) when you need stale
backup alerts. Failed jobs remain CRIT regardless of the age policy.

Existing configured Checkmk services keep their identities, except genuinely
duplicated job names may get a clearer suffix (`[backup]` or `[snapshot]`).

Installing the package from GitHub **does not enable automatic updates**.
You can re-download and install a newer MKP as it is published.

## Caveats

- Morpheus and Kasten job discovery is execution-history based (default look-back: 14 days); jobs with no session in this window are not discoverable. Increase look-back for less frequent jobs, mindful of collection time.
- CustomPlatform does not uniquely mean Morpheus or Kasten; metadata is preserved.
- `/api/v1/jobs/states` may not expose schedules or last completion time for every job type.
- A `Valid` license does not guarantee every REST endpoint is licensed or accessible to the API user.
- REST service probes show collection time and failed mandatory endpoints.
- SSL certificate validation should be enabled with a trusted CA in production.

## License

GPL-2.0-only. Copyright (c) 2026 Pawel Wladzinski.
