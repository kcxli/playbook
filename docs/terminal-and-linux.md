# Terminal & Linux — a practical guide for this project

A focused, copy-pasteable reference. Everything here uses *this project's* real
paths and commands, so you learn by doing the actual work. Read top to bottom
once; after that, use it as a cheatsheet.

> **macOS vs Linux:** your laptop (macOS) and the server (Linux) share the same
> terminal basics — the commands below work on both. Where they differ (mostly
> installing system software) it's called out.

---

## 1. The basics: where am I, what's here, moving around

When you open a terminal you get a **prompt** waiting for a command. Three
commands answer "where am I and what's here":

```bash
pwd                 # "print working directory" — the folder you're in
ls                  # list files here
ls -la              # list ALL (incl. hidden .files), long format (sizes, dates)
cd project-playbook # "change directory" — move INTO a folder
cd ..               # move UP one folder (.. means "parent")
cd ~                # go to your home folder (~ means /Users/kateli)
cd -                # jump back to the previous folder
```

**Paths** are how you name a file/folder:

| Path | Means |
|------|-------|
| `applicants/test.json` | *relative* — from where you currently are |
| `/Users/kateli/Desktop/project-playbook` | *absolute* — full path from the root `/` |
| `~/Desktop/project-playbook` | `~` = your home, so same as above |
| `.` | the current folder |
| `..` | the parent folder |

> **Two time-savers you'll use constantly:**
> - **Tab completion**: type the first few letters of a file/folder and press
>   `Tab` — the shell finishes it for you (press Tab twice to see options).
> - **History**: press the **Up arrow** to recall previous commands. `Ctrl-R`
>   then typing searches your history.

---

## 2. Looking at and moving files

```bash
cat README.md              # dump a whole file to the screen
less SPEC.md               # page through a long file (arrows to scroll, q to quit)
head -n 20 applicants/test.json   # first 20 lines
tail -n 20 applicants/test.json   # last 20 lines

cp a.json b.json           # copy a.json to b.json
mv old.yaml new.yaml       # move/rename
mkdir playbooks/drafts     # make a new folder
```

**Deleting is permanent — there is no Recycle Bin in the terminal:**

```bash
rm somefile.txt            # delete a file (gone for good)
rm -r somefolder           # delete a folder and everything in it
```

> ⚠️ Double-check the path before you run `rm -r`. There is no undo. Never run
> `rm -rf /` or `rm -rf ~` — those wipe everything.

---

## 3. The virtual environment (venv) — what it is and why

A **venv** is a private, project-local copy of Python and its packages. Without
it, `pip install` dumps packages into your system Python and different projects
fight over versions. With it, this project's packages live in `.venv/` and touch
nothing else. The server gets an *identical* environment from `requirements.txt`.

This project's venv already exists at `.venv/`. There are two ways to use it:

```bash
# Option A — "activate" it (your prompt changes to show (.venv)):
source .venv/bin/activate
python -m playbook_runner ...     # now plain `python` = the venv's python
deactivate                        # leave the venv when done

# Option B — call the venv's python directly, no activation (what the README uses):
.venv/bin/python -m playbook_runner ...
```

Both are fine. Option B is explicit and great for scripts/cron; Option A is
comfier for an interactive session. **Recreating it from scratch** (e.g. on the
server) is in [requirements.txt](../requirements.txt) — read the comment block at
the top. The short version:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium    # downloads the browser
```

> `pip` installs Python packages; `playwright install` downloads the actual
> browser binary. They're two separate steps — forgetting the second is the #1
> "it works on my laptop but not the server" bug.

---

## 4. Running this project

```bash
# Draft a new playbook: paste tools/form-extractor.js into the DevTools console
# on the form page, then hand its output to Claude.

# Check a playbook resolves against an applicant, without a browser:
.venv/bin/python -m playbook_runner playbooks/uthealth.playbook.yaml \
    -d applicants/test.json --validate

# Run it for real, slowly, with a visible browser (great while testing):
.venv/bin/python -m playbook_runner playbooks/uthealth.playbook.yaml \
    -d applicants/test.json --slow-mo 300 --screenshot-dir ./shots
```

The `\` at the end of a line means "this command continues on the next line" —
purely for readability. You can also type it all on one line.

---

## 5. Power moves: pipes, redirection, and loops

**The pipe `|`** sends one command's output into another:

```bash
ls playbooks/ | wc -l          # count files in playbooks/ (wc -l = count lines)
cat applicants/test.json | grep email   # show only lines containing "email"
```

**Redirection `>` and `>>`** sends output to a file instead of the screen:

```bash
.venv/bin/python -m playbook_runner wizard "<url>" > draft.yaml   # write (overwrite)
some_command >> log.txt        # append to a file
some_command 2> errors.txt     # send only errors (stderr) to a file
```

**A `for` loop** repeats a command over many items — e.g. run one playbook for
every applicant file (this is the batch pattern from the README):

```bash
for who in applicants/*.json; do
  .venv/bin/python -m playbook_runner playbooks/uthealth.playbook.yaml -d "$who" --validate
done
```

`*.json` is a **glob** — the shell expands it to every matching file. `$who` is a
**variable** holding the current item each time through the loop.

**Stopping things:** `Ctrl-C` cancels the running command. `Ctrl-C` is your
emergency brake if a browser run goes sideways.

---

## 6. Linux & the server: the extra pieces

On the server you'll meet a few things macOS hides:

### Connecting in
```bash
ssh kateli@server-address      # open a remote terminal on the server
exit                           # disconnect
scp file.json kateli@server:/path/   # copy a file TO the server
```

### Permissions (who can read/run a file)
`ls -l` shows permissions like `-rwxr-xr--`. The letters mean read/write/execute
for owner, group, others. You'll mostly need:

```bash
chmod +x script.sh             # make a script executable
chmod 600 secrets.json         # owner read/write only (lock down a sensitive file)
```

### Installing system software (Debian/Ubuntu)
```bash
sudo apt update                # refresh the package list
sudo apt install python3-venv  # install a system package
.venv/bin/python -m playwright install-deps chromium   # browser's OS libraries
```

`sudo` = "do this as the admin (root)". It'll ask for a password. Use it only
when a command genuinely needs system-level access (installing software, etc.).

### Headless: there's no screen on a server
A server has no display, so the browser can't pop open a window. Always pass
`--headless` there:

```bash
.venv/bin/python -m playbook_runner playbooks/x.playbook.yaml -d data.json --headless
```

### Keeping a long job running after you log off
If you close the SSH session, your command normally dies with it. To keep it
alive, use `tmux` (a terminal that survives disconnects):

```bash
tmux                 # start a persistent session
# ... run your long command ...
# press Ctrl-b then d  to "detach" (leave it running)
tmux attach          # later: reconnect to it
```

### Seeing and stopping processes
```bash
ps aux | grep playbook    # find running playbook processes
top                       # live view of what's using CPU/memory (q to quit)
kill <PID>                # stop a process by its number (PID, from ps)
df -h                     # free disk space
```

---

## 7. Git — saving your work

This project is a git repo. The everyday loop:

```bash
git status                 # what have I changed?
git diff                   # show the actual line-by-line changes
git add -A                 # stage all changes for the next commit
git commit -m "Add Stanford playbook"   # save a snapshot with a message
git log --oneline          # browse past commits
```

> Commit often with clear messages. A commit is a restore point you can always
> come back to.

---

## 8. Quick cheatsheet

| I want to… | Command |
|------------|---------|
| See where I am | `pwd` |
| List files | `ls -la` |
| Go into / up a folder | `cd name` / `cd ..` |
| Read a file | `less file` (q to quit) |
| Copy / move / delete | `cp` / `mv` / `rm` (careful!) |
| Use the project's Python | `.venv/bin/python …` |
| Draft a playbook | paste `tools/form-extractor.js` into DevTools console |
| Check a playbook | `… -m playbook_runner <pb> -d <data> --validate` |
| Cancel a running command | `Ctrl-C` |
| Recall a past command | Up arrow, or `Ctrl-R` to search |
| Finish a filename for me | `Tab` |
| Connect to the server | `ssh user@host` |
| Keep a job alive over SSH | `tmux` (detach: `Ctrl-b` `d`) |
| Save my work | `git add -A && git commit -m "…"` |

When you're stuck, most commands explain themselves: `ls --help`, or
`man ls` (the manual; `q` to quit).
