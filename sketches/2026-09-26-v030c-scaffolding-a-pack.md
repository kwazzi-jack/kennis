# Scaffolding a pack

Milestone / step: milestone 7 (packs), unit 3
Date: 2026-09-26

## What I am about to do

`kennis pack init --id boepie --name "stimela pipelines"`, which writes a
`.ken.yml` carrying the editor header line and an identity block filled from
its arguments. Design section 3, and section 18 for the header.

## How I expect it to work

**The file is written as text, not dumped from a model.** `yaml.dump` of a
`Pack` would produce a valid file with no comments, keys in whatever order
the dumper chooses, and no room for the section headings a human author
reads. A pack file is meant to be edited by hand for the rest of its life,
so the scaffold is a template string with the identity interpolated, and
`load_pack` is run over the result before it is written - so the scaffold
cannot be a file kennis itself would refuse.

**The header line is the point of the command.** Section 18: an author with
no kennis installed gets completion and inline errors from
`redhat.vscode-yaml` because of one comment at the top of the file. It names
the raw GitHub URL for `schema/ken-1.json`, versioned so schema 2 is a new
file.

**Refuses rather than converges.** `context init` is re-runnable and
restores a missing scaffold file, because a bundle is a directory of many
files and the command's job is to make it whole. A pack file is one file
holding hand-written declarations, and rewriting it would delete them, so
`init` refuses when the path exists and names nothing to force. Overwriting
is what `rm` is for.

**Where it writes.** A positional path, defaulting to `<id>.ken.yml` in the
working directory, because the provider's own release layout decides where
its pack lives and kennis has no opinion.

## What I expect to be uncertain or difficult

**What `version` gets.** `PackIdentity.version` is required, so the scaffold
must carry one. `--version` with a default of `0.1.0` is the obvious answer;
the risk is that a provider never changes it and ships every release as
0.1.0, which the diff in section 5 does not depend on but `pack status`
reports.

**Whether the URL belongs in the code.** It names a GitHub repository, which
is a fact about where kennis is published rather than about packs. If it
moves, every pack scaffolded before the move carries a dead link in a
comment - harmless to kennis, which reads its own local copy, and not
harmless to the editor integration the line exists for.

## What actually happened that I did not expect

**The version question answered itself, the URL question did not, and a
third thing appeared that I had not considered at all.**

`--pack-version` rather than `--version`, because click's own
`--version` is already on the group and the two would collide. Default
`0.1.0`. The risk I named - a provider never changing it - is real and not
mine to solve: nothing in resolution depends on it, `pack status` reports
it, and a provider that ships every release as 0.1.0 has a problem kennis
cannot detect.

The URL is one constant in `scaffold.py` naming
`kwazzi-jack/kennis`. I left it there rather than in settings, because a
setting for it would imply a user should change it, and they should not:
the line exists so an editor validates against *this* kennis's schema.

**The thing I had not considered: a good error and a bad hint.** Running
`pack init` twice printed

    error: boepie.ken.yml already exists, ...
      hint: run `kennis pack validate`

The message is right and the hint is wrong. It comes from
`PackInvalid.default_resolution`, which is correct for almost every raise
site and nonsense for this one - validating the file you just failed to
overwrite answers a question nobody asked. Rule 4.4 is about commands that
do not run; this one runs and does not help, which no test noticed because
every test asserted on the message. Fixed with `resolution=None` at that
raise site and a message that says what to do in words.

**And a deprecation.** `CliRunner.isolated_filesystem` is deprecated in
click 9, and `filterwarnings = ["error"]` turns that into a failing test
the moment it is used. `monkeypatch.chdir(tmp_path)` instead. The setting
paid for itself immediately: a deprecation found while writing the test
rather than in a release where the command stopped working.
