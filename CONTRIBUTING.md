# Contributing to Golf Sim Analytics

Thanks for your interest in improving Golf Sim Analytics — a Windows desktop
analytics companion for [GSPro](https://gsprogolf.com/) golf simulators.

## Ways to help

- **Bug reports** — open an issue with your Windows version, what you did, what
  you expected, and the relevant lines from `logs/simanalytics.log`.
- **Launch-monitor / GSPro coverage** — mappings and parsing fixes for setups
  other than the maintainer's are especially welcome (e.g. new `ClubIndex`
  values, CSV column spellings, `connectType` strings).
- **New dashboards or analytics**, UI polish, performance, tests.

## Development setup

Requires Windows and Python 3.11+.

```
pip install -r requirements.txt
python app.py           # run the app
python -m pytest        # run the test suite
```

No simulator handy? Launch the app and open **⚙ Settings → Use sample data** to
explore the two bundled synthetic datasets.

## Workflow

1. **Fork** the repo and create a topic branch (`fix/…`, `feat/…`).
2. Make your change. Keep it focused — one logical change per PR.
3. **Add or update tests** under `tests/` and make sure `python -m pytest`
   passes. Chart code has smoke tests that render every dashboard; data code is
   unit-tested in isolation from Tkinter.
4. Open a **pull request** against `main` with a clear description of the what
   and why. Direct pushes to `main` are not accepted — everything lands via PR.

## Style

- Match the surrounding code: this project favors clear names, short functions,
  and comments that explain *why* rather than *what*. Look at a neighboring
  module before adding a new one.
- Keep Tkinter out of the `data/` layer so it stays unit-testable; charts take a
  plain DataFrame and a matplotlib figure.
- Windows-specific behavior (DPI awareness, dark title bar, GSPro paths) is
  expected — this app is Windows-only by design.

## Privacy — please read before touching contribution code

Contribution to OpenGolfLab is **opt-in and anonymized**: only mapped per-shot
metrics are shared, and names, file paths, timestamps, and identifiers are
dropped by construction (see `contribute.py`). **Do not add anything that would
send personally identifying information**, and never commit runtime state such
as `.contributor_id`, `.contribute_consent`, `settings.json`, or any real shot
data (`raw_csvs/`, `parquet_data/`) — these are gitignored for a reason.

## License

By contributing, you agree that your contributions are licensed under the
project's [GNU AGPL-3.0](LICENSE) license, the same terms as the project
itself. Commercial *use* of the app is welcome; the license only requires that
distributed or hosted modifications share their source.
