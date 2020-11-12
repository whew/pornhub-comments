import requests
import argparse
import bs4
import json
import re
import os
import urllib.parse

try:
    import js2py
except ImportError:
    js2py = None

_RE_VALID_URL = re.compile(r'(?:https?://(?:www.)?pornhub.com/view_video?viewkey=)?([\w\d]+)')

_URL_BASE     = 'https://www.pornhub.com'
_URL_VIDEO    = 'https://www.pornhub.com/view_video.php'
_URL_COMMENTS = 'https://www.pornhub.com/comment/show'

def _request_pornhub(method, url, kwargs=None, is_json=False, session=None):
    session = session or requests.session()
    kwargs = kwargs or {}

    send_request = {'get': session.get, 'post': session.post}[method.casefold()]
    response = send_request(url, **kwargs)
    response.raise_for_status()

    if is_json or 'application/json' in response.headers['Content-Type']:
        return response.json()

    soup = bs4.BeautifulSoup(response.text, 'html5lib')
    body = soup.find('body')

    onload = body and body.get('onload')
    # no javascript wall
    if onload == None:
        return soup

    assert js2py, f'Pornhub blocked our request for {url}, install Js2Py (https://pypi.org/project/Js2Py/) to circumvent'

    # page wants a cookie and it calculates it with javascript
    # if Pornhub changes how this works, this solution will break
    js_context  = js2py.EvalJs()
    js_context.execute('var document = {location: {reload: function() {}}};')
    js_context.execute(soup.find('script').text)
    js_context.execute(onload)

    re_match = re.fullmatch(r'RNKEY=([^;]+); path=/', js_context.document['cookie'])
    hostname = urllib.parse.urlparse(url).netloc
    cookie = requests.cookies.create_cookie(domain=hostname,
                                            name='RNKEY',
                                            value=re_match.group(1),
                                            path='/')
    session.cookies.set_cookie(cookie)

    response = send_request(url, **kwargs)
    session.cookies.clear(hostname)
    response.raise_for_status()

    if is_json or 'application/json' in response.headers['Content-Type']:
        return response.json()

    soup = bs4.BeautifulSoup(response.text, 'html5lib')
    assert 'onload' not in soup.find('body').attrs, "failed to circumvent Pornhub's Javascript wall"

    return soup

def _get_video_info(url, session=None):
    session = session or requests.session()

    video_id = _RE_VALID_URL.fullmatch(url).group(1)
    video_url = _URL_VIDEO.format(video_id)

    soup = _request_pornhub('GET', video_url, kwargs={'params': {'viewkey': video_id}}, session=session)
    numeric_id = int(soup.find('div', {'id': 'player'})['data-video-id'])
    title = soup.find('h1', {'class': 'title'}).find('span')
    title = re.fullmatch(r'<span[^>]*>(.*)</span>', str(title)).group(1)

    return {'url': video_url, 'numeric_id': numeric_id, 'video_id': video_id, 'title': title}

def _extract_num_comments(soup):
    n_comments_tag = soup.find('h2').find('span')
    n_comments = int(n_comments_tag.text.strip('()'))
    return n_comments

def _get_comments_html(numeric_id, sort_popular=True, session=None):
    session = session or requests.session()

    comments_html = []
    params = {'id': numeric_id, 'limit': 200, 'popular': int(sort_popular), 'what': 'video', 'page': 1}
    while True:
        soup = _request_pornhub('POST', _URL_COMMENTS, kwargs={'params': params}, session=session)

        # get the number of comments (only on the first page)
        if params['page'] == 1:
            n_comments = _extract_num_comments(soup)

        # on page 1 there are more div tags than other pages, this gets rid of them
        soup = soup.find('div', {'id': 'cmtContent'}) or soup.find('body')
        for tag in soup.find_all('div', recursive=False):
            # tag contains many comments ("View More" on the website)
            if 'showMoreParentsSlide' in tag['class']:
                children = tag.find_all('div', recursive=False)
                comments_html.extend(children)
            # tag is a comment
            else:
                comments_html.append(tag)

        # if the `page` param gets too high, the HTML is completely blank
        if len(soup) == 0:
            return n_comments, comments_html

        params['page'] += 1

def _parse_comment_html(comment_html):
    comment = {'replying_to': None}
    comment['comment_id'] = int(re.fullmatch(r'commentTag(\d+)', comment_html['class'][2]).group(1))

    user_wrap, comment_message, _ = comment_html.find().find_all(recursive=False)
    username_wrap = user_wrap.find('div', {'class': 'usernameWrap'})
    username_badges_wrapper = user_wrap.find('span', {'class': 'usernameBadgesWrapper'})
    date = user_wrap.find('div', {'class': 'date'})
    comment_message_span = comment_message.find('span')
    vote_total = comment_message.find('span', {'class': 'voteTotal'})

    user_profile = user_wrap.find('a')

    comment['user_id'] = int(username_wrap['data-userid'])
    comment['user_json_url'] = urllib.parse.urljoin(_URL_BASE, username_wrap['data-json-url'])
    comment['user_name'] = username_badges_wrapper.text
    comment['user_profile'] = user_profile and urllib.parse.urljoin(_URL_BASE, user_profile['href'])
    comment['date'] = date.get_text(strip=True)
    comment['body'] = re.fullmatch(r'<span>(.*)</span>', str(comment_message_span), flags=re.DOTALL).group(1)
    comment['score'] = int(vote_total.text)

    return comment

def _parse_comments_html(comments_html):
    comments = []
    for tag in comments_html:
        # tag is one comment
        if 'commentBlock' in tag['class']:
            comment = _parse_comment_html(tag)
            comments.append(comment)
        # tag is several comment replies
        else:
            parent_id = int(re.fullmatch(r'childrenOf(\d+)', tag['class'][1]).group(1))
            for child in tag.find_all('div', {'class': 'commentBlock'}):
                comment = _parse_comment_html(child)
                comment['replying_to'] = parent_id
                comments.append(comment)

    return comments

def _get_users_from_comments(comments, session=None):
    session = session or requests.session()

    user_json_url = {}
    for comment in comments:
        user_json_url.setdefault(comment['user_id'], comment.pop('user_json_url'))

    users = {}
    for user_id in user_json_url:
        url = user_json_url[user_id]
        users[user_id] = _request_pornhub('GET', url, is_json=True, session=session)

    return users

def get_comments(url, sort_popular=True, get_users=True, session=None):
    session = session or requests.session()

    video_info = _get_video_info(url, session)
    n_comments, comments_html  = _get_comments_html(video_info['numeric_id'], sort_popular, session)
    comments = _parse_comments_html(comments_html)

    if get_users:
        users = _get_users_from_comments(comments, session)
    else:
        users = None
        # remove the user JSON url from each comment since
        # _get_users_from_comments does this otherwise
        for comment in comments:
            comment.pop('user_json_url')

    return {'video': video_info,
            'n_comments': n_comments,
            'comments': comments,
            'users': users}

def _sanitize(string):
    '''
    Make a string more likely to be a safe filename
    No guarantees though
    '''
    return re.sub(r'[/\:]', '', string)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download comments from Pornhub.com',
                                     add_help=False,
                                     usage='\b\b\b\b\b\b\bUsage: pornhub_comments.py [-h] [-c] [-x URL] [-o TEMPLATE] URL [URL ...]',
                                     epilog='Output template keys:\n  video_id  e.g. ph5d797f173d256\n  id        e.g. 247797731\n  title     e.g. 素人,えんじょ,JK,フェラ,手コキ,射精,制服\n\nExample usage:\n  python3 pormhub_comments.py https://www.pornhub.com/view_video.php?viewkey=ph5d797f173d256\n  python3 pornhub_comments.py ph5d797f173d256',
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser._optionals.title = 'Options'
    parser.add_argument('-h', '--help', help='Show this help message and exit', action='help', default=argparse.SUPPRESS)
    parser.add_argument('-c', '--skip-users', action='store_true', help="Don't download information about commenters. This is significantly faster for videos with lots of comments.")
    parser.add_argument('-x', '--proxy', metavar='URL', help='URL of the proxy server to use')
    parser.add_argument('-o', '--output', metavar='TEMPLATE', default='{title}-{video_id}.json', help="Output filename template, default '{title}-{video_id}.json'")
    parser.add_argument('urls', metavar='URL', nargs='+', help=argparse.SUPPRESS)
    args = parser.parse_args()

    session = requests.Session()
    session.proxies = {'http': args.proxy, 'https': args.proxy}
    session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; rv:78.0) Gecko/20100101 Firefox/78.0'

    for url in args.urls:
        result = get_comments(url, get_users=not args.skip_users, session=session)

        info = {'video_id':   result['video']['video_id'],
                'numeric_id': result['video']['numeric_id'],
                'title':      result['video']['title']}
        fn = _sanitize(args.output.format(**info))
        directory = os.path.split(fn)[0]
        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(fn, 'w') as fp:
             json.dump(result, fp, indent=2, ensure_ascii=False)
