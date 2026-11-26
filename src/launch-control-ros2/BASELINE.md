# BK Baseline Provenance

- Baseline branch: `baseline/bk`.
- Frozen tag: `baseline-bk-20261015`.
- Parent: `d843031`, the existing master snapshot. Earlier history is retained.
- Program source: local `launch_control/bk/launch_control.py`.
- Program Git blob: `9b2e7badd7831f47b31c4c5f1df1dd1043ec1b62`.
- Program version: `ros2-20260326-1`. Contents are preserved byte for byte.
- The backup contains no configuration, interface, or build files.

## Compatibility Files

Surrounding files are adapted from the parent snapshot, not claimed to be the
original author's complete distribution:

- Existing interface definitions are provided as `data_msgs` to match backup
  imports. This minimal package does not reconstruct any other original interfaces.
- Build dependencies follow that name; the backup does not use `diagnostic_msgs`.
- Extension configuration has five fields: ID, command, output, log rotation,
  and `check_status`. There is no sixth `force_kill` field.
- `open_piper` retains name-based SIGKILL behavior.
- Robot and auto-start configuration, launch entry, static run script, and static
  services are inherited from the parent snapshot.
- The unchanged backup shebang requires `python3.10`.

## Development History

Keep `master` and `0_1_0a1` unchanged. Development starts from this frozen baseline
on `dev/rosenyin`. Compare the preserved results or the new development branch:

```bash
git diff baseline-bk-20261015 0_1_0a1
git diff baseline-bk-20261015 dev/rosenyin
git log --oneline baseline-bk-20261015..dev/rosenyin
```

Known legacy behavior is preserved, not silently fixed. The local backup does
not establish a complete upstream release or authorship. Hardware-level behavior
needs separate verification. Do not build alongside another package named
`data_msgs`; use an isolated workspace or a matching external interface package.
