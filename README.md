# pornhub-comments
Get comments from Pornhub videos

### Requirements
* `Python 3.6` at least
* `python-requests`
* `python-bs4`
* [`python-js2py`](https://github.com/PiotrDabkowski/Js2Py) (optional) Sometimes Pornhub doesn't give you the page you requested, instead it serves a page with some Javascript on it that calculates a cookie value and only lets you continue with that cookie. In a web browser this isn't a problem, it just takes a few seconds longer to load and you don't usually notice. `pornhub_comments.py` works without this dependency but will fail if it encounters this behaviour.

### Usage
`python3 pornhub_comments.py [-h] [-c] [-x URL] [-o TEMPLATE] URL [URL ...]`

#### Options
* `-h`, `--help` Help
* `-c`, `--skip-users` Don't download information about commenters. This is significantly faster for videos with lots of comments.
* `-x`, `--proxy` URL of the proxy server to use
* `-o`, `--output` Output filename template, default `'{title}-{video_id}.json'`

#### Output template keys
* `video_id`, e.g. `ph5d797f173d256`
* `numeric_id`, e.g. `247797731`
* `title`, e.g. `素人,えんじょ,JK,フェラ,手コキ,射精,制服`

#### Example usage
* `python3 pornhub_comments.py https://www.pornhub.com/view_video.php?viewkey=ph5d797f173d256`
* `python3 pornhub_comments.py ph5d797f173d256`

### Output
Output is JSON and looks like this:
```
{
  "video": {..},
  "n_comments": ..,
  "comments": [..],
  "users": {..}
}
```
[There's an example of this in the repo.](example.json)

`n_comments` is the number of comments as indicated by Pornhub. There's no guarantee that it means anything.

### Usage within Python
```
import requests
import pornhub_comments

session = requests.session() # optional
comments = pornhub_comments.get_comments('https://www.pornhub.com/view_video.php?viewkey=ph5d797f173d256', session=session)
```

### To do
* More explanatory comments
* Progress bar
* Option to download in most recent order
* Properly sanitize filenames
