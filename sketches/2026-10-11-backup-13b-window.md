# 13b. Backup: the window's section

Milestone / step: milestone 13, second half (`design/plan.md`), #413, #420
Date: 2026-10-11

## What I am about to do

The Backup section of the settings page: choose the folder, see whether
it is usable and when the backup was last written, back up now, test the
backup with the password, and read how to restore. Everything goes
through 13a's engine and operation. Nothing about the archive is decided
here.

## How I expect it to work

**A section of `/settings`, `data-section="backup"`, with `id="backup"`**
so the palette and a link can reach it. It is drawn from
`check_backup(folder)` and the words in `render/backup.py`, so the
window says what `kennis backup check` says.

- **Folder.** A text field named `backup.folder`, with 11d's chooser
  (`/browse?target=backup.folder&folders=1`, the target admitted by
  `chooser_target`). `BACKUP_CONTENTS` stands beside it, because that is
  where the decision is made. `POST /settings/backup` writes it through
  `apply_answers`, the same writer as everything else. It refuses a path
  that is not a folder, because the chooser can also hand over a file.
- **State.** `describe_folder` and `describe_archive`, or "no backup
  folder is set".
- **Back up now.** Two password fields, which must agree, posted to
  `POST /backup`. That starts a job, `kind="backup"`, through `_started`,
  so it appears in the strip and refuses while another job runs. The
  result is a `BackupReport`, which `_shown_result` matches. Empty or
  differing passwords, and no folder, are refused before a job starts.
- **Test.** One password field, posted to `POST /settings/backup/test`,
  which redraws the section with `describe_verified`. A failure is drawn
  in the error role.
- **Restore** is not a control: a sentence and `kennis backup restore
  <file>`. A restore replaces the corpus a window is showing, so it
  belongs to a command run while no window is open.

**The password never comes back.** No password field is ever drawn
with a value. The answer to every POST is checked for the password in
the tests. It reaches the job only as an argument to
`back_up_corpus`, and the log records events, not arguments.

## What I expect to be uncertain or difficult

- A password manager offering to save "a password" for the loopback
  origin. `autocomplete="new-password"` on the pair and
  `"current-password"` on the test field are the honest hints. Whether
  to suppress the offer is not kennis's to decide.
- A section that redraws by htmx inside a page that also holds the two
  other sections' forms: each form has to carry its own target and
  `hx-disinherit` (#430).
- The job's closure holds the password for as long as the job object
  is kept (an hour). The `Job` record holds `work` only while it runs,
  if at all. Measure it rather than assume.

## What actually happened that I did not expect

- **The section and the strip disagreed on one page.** After Back up
  now, the strip read "Backed up to ..." while the section beside it
  still read "no backup has been written there yet". The suite could
  not see this, because each test asks one route. The walk did. A
  finished job now names a part of the page it changed
  (`ShownJob.redraws`), and the outcome carries a hidden hook for it.
- **htmx 2.0.4 never fires `load` with a filter.** The first hook was
  `hx-trigger="load[document.getElementById('backup')]"`. Injected
  beside a plain `load` in the same page, the filtered one sent nothing
  and the plain one fired. The check moved into `progress.js`: if the
  page has the element, `htmx.ajax` redraws it.
- **The guard matters more than it looks.** Without `!target`, a backup
  finished on a page with no Backup section swapped the section into
  that page and took the strip with it, so the outcome never appeared.
  Measured once with the guard removed. The suite can only assert the
  guard's text, so the behaviour stays a walk check.
- **The password is not retained.** `Job` keeps `result`, `error` and
  the event history, not `work`, so the closure holding the password
  is released when the thread ends. Settled by reading `jobs.py`. The
  log of a walk that backed up and tested twice does not contain it.
- **Outcomes beside their controls.** At the head of the section,
  "the password is wrong" read as being about the whole section. Each
  answer is now drawn under the form that produced it, and the tests
  look for it there.
- **The walk misread its own page twice.** `goto` to the address
  already shown only scrolls to the fragment, so a "redrawn" state was
  read from the stale page, and an earlier "Saved." was taken for the
  test's answer. A walk asserts on a change it waited for, not on
  whatever matches a selector.
- 18 injections: all caught after the guard assertion was added. One
  produced an error beside its failure: the job's thread raised a
  `TypeError` for a folder of `None`. The failure was the intended
  test.
