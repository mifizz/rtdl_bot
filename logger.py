import requests, logging, time
from typing import Literal

logger = logging.getLogger(__name__)
colored: bool = False
ntfy_topic: str = None

colors = {
    'i':'\033[0m',  # default
    'e':'\033[31m', # red - error
    's':'\033[32m',  # green - success
    'w':'\033[33m', # yellow - warning
    'o':'\033[90m', # gray - other
    'u':'\033[90m'  # gray - undefined
}

tags = {
    'i':'info ', # info tag
    'e':'error', # error tag
    's':'succs', # success tag
    'w':'warng', # warning tag
    'o':'other', # tag for other information
    'u':'undef'  # undefined tag
}

ntfy_tags = {
    'i':'speech_balloon',   # info tag
    'w':'warning',          # warning tag
    'e':'x'                 # error tag
}

priorities = {
    'e':'high',             # high priority
    'w':'default',          # default priority
    'i':'low',              # low priority
}

def init_logger(
    filename: str, 
    colored_output: bool = False, 
    ntfy_topic_str: str = None):
    global colored, ntfy_topic

    # colored log output
    colored = colored_output
    # update logger config
    logging.basicConfig(filename=filename, format="%(message)s", level=logging.INFO)
    # separator
    logger.info('-----------------------------------------')

    # test ntfy
    if ntfy_topic_str != None:
        # make a post request
        test_ntfy = requests.post(
            f"https://ntfy.sh/{ntfy_topic_str}",
            data=f"This is a test message to check if provided ntfy.sh topic is correct. Bot is now launching...",
            headers={
                "Title": "ntfy.sh topic test",
                "Priority": "min",
                "Tags": f"{ntfy_tags['i']}"
            }
        )
        # topic is ok
        if test_ntfy.ok:
            # enable/disable ntfy.sh (global)
            ntfy_topic = ntfy_topic_str
            log('o', 'w', "ntfy.sh topic is ok")
        # topic incorrect
        else:
            ntfy_topic = None
            log('e', 'r', "ntfy.sh topic is NOT ok! notifications disabled")

def log(
    tag: Literal[tags.keys],
    text: str,
    will_notify: bool = False,
    post_title: str = 'rtdl_api notification',
    post_tag: Literal[ntfy_tags.keys] = 'i'):
    
    # concat log message and print it
    if colored:
        output = '\033[90m' + time.asctime() + '\033[0m ' + colors[tag] + '[' + tags[tag] + ']\033[0m > ' + text
        print(output)
    else:
        output = '['+ tags[tag] + '] > ' + text
        print(output)
    
    # write message in log
    if tag == 'e':      # error
        logger.error(output)
    elif tag == 'w':    # warning
        logger.warning(output)
    else:               # info
        logger.info(output)
    
    # post message to ntfy.sh if needed
    if ntfy_topic != None and will_notify:
        ntfy_post(post_tag, post_title, text)

def ntfy_post(
    tag: Literal['i', 'w', 'e'],
    title: str,
    text: str):
    
    requests.post(
        f"https://ntfy.sh/{ntfy_topic}",
        data=f"{text}",
        headers={
            "Title": f"{title}",
            "Priority": f"{priorities[tag]}",
            "Tags": f"{tags[tag]}"
        }
    )