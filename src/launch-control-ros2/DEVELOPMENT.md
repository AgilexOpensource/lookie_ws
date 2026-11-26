# Development Provenance

`dev/rosenyin` starts from frozen baseline `ace69f4`, tagged
`baseline-bk-20261015` on `baseline/bk`. Integration commit `ec76bc8` restores
the application and README byte for byte from original master `d843031`.
Feature commit `ad25ffc` then carries original `eb8a659` with `cherry-pick -x`.
The final application and README match `0_1_0a1` byte for byte; tests and
provenance files are the development-specific additions. `BASELINE.md` remains
the unchanged historical snapshot record. Existing branch refs remain intact.

The grouped history integration restores standalone `launch_control_msgs`
interface names, source cleanup, diagnostics (`4cf7077`), process management
and launch-failure handling (`1ed8a4f`, `4a07f9a`), and startup environment
handling (`d843031`). The fifth configuration field, `check_status`, already
exists in the backup; it is not newly introduced. A sixth field was added
after that backup, first as `force_kill`. The current source reads it as
`shutdown_timeout`: seconds to wait after `SIGTERM` before `SIGKILL`, default 90.

Service generation, generated startup script, startup user handling, and their
documentation remain a separate feature commit, not part of the integration.

Compare committed development and the preserved comparison branch:

```bash
git diff baseline-bk-20261015..dev/rosenyin
git diff baseline-bk-20261015..0_1_0a1
```

Ref-to-ref comparisons do not include uncommitted work. The integration groups
existing work honestly; consult the preserved original commits for finer history.

Regression tests retain baseline byte equality when version
`ros2-20260326-1` and the local backup are present. Master assertions cover
interface and diagnostic differences, the sixth field, and missing-executable
failure. Both versions retain the five-field parser and owned temporary sleep
launch/stop checks. Tests do not instantiate a ROS node or access hardware.

Run against the verified isolated feature build:

```bash
source /opt/ros/humble/setup.bash
source /tmp/launch-control-feature-20261015/install/setup.bash
cd /home/agilex/develop/launch_control/launch_control_ws2/src/launch-control-ros2
/usr/bin/python3 -m unittest discover -s tests -v
```

## Verification

- Baseline: isolated Humble build of `data_msgs` and `launch_control`; all five
	original baseline tests passed, including byte equality with the local backup.
- Master integration: isolated build and seven regression tests passed.
- Feature migration: isolated build and seven regression tests passed;
	application and README comparison with `0_1_0a1` is empty.
- Both static and generated run scripts passed `bash -n`.
- Builds use `/tmp/launch-control-{bk,dev,feature}-20261015` rather than the
	existing workspace build/install directories. These temporary outputs can
	disappear; rebuild when needed.
- No user configuration, systemd installation, robot node, or hardware was
	modified or started. Actual ROS communication, boot behavior, and hardware
	still need deployment validation.

The checkout is returned to `baseline/bk` after verification. Existing install
directories do not automatically change with a branch checkout. For the old
version, source `/opt/ros/humble/setup.bash` and the isolated baseline install
`/tmp/launch-control-bk-20261015/install/setup.bash` in a fresh terminal.
Nothing has been pushed. Publish the new branches and frozen tag explicitly
when ready; do not force-push or move the existing branch refs.
