import requests, telebot, argparse, dotenv, os, threading, json, time, ffmpeg
from pathlib import Path
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from fake_useragent import UserAgent
# local
import logger, exception_handler
import rtdl_api as rdl
from logger import log
from exception_handler import BotExceptionHandler

# init argument parser
arg_parser = argparse.ArgumentParser(
    prog='bot.py',
    description='Telegram bot for downloading videos from rutube.ru'
)
# add arguments to parser
arg_parser.add_argument('-c', '--colored', action='store_true', help='enable colored output in logs')
arg_parser.add_argument('-t', '--token', help='token of your telegram bot')
arg_parser.add_argument('-l', '--localport', help='port of your local telegram api')

# parse arguments
args = arg_parser.parse_args()

# init logger
logger.init_logger("log.log", args.colored)

# load token from .env
# or use token from args
dotenv.load_dotenv()
if args.token:
    TOKEN = args.token
elif os.getenv("TOKEN"):
    TOKEN = os.getenv("TOKEN")
else:
    log('e', "No token provided - aborting...")
    exit(1)

# try to launch bot
try:
    if args.localport:
        telebot.apihelper.API_URL = f"http://0.0.0.0:{args.localport}" + "/bot{0}/{1}"
    exception_handler.set_token(TOKEN)
    bot = telebot.TeleBot(TOKEN, exception_handler=BotExceptionHandler())
except Exception as e:
    log('e', f"Failed to launch bot: {e}")
    exit(2)

# init new requests session
session = requests.Session()

### METHODS

def update_session() -> int:
    global session

    ua = UserAgent(browsers=["Firefox", "Chrome"])
    test_api_url = "https://rutube.ru/video/4e1db85ae675260ca419924462182261/"
    headers = {
        "Accept-Language": "en-US,en;q=0.5",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Host": "rutube.ru",
        "Pragma": "no-cache",
        "Referer": "https://rutube.ru/",
        "User-Agent": f"{ua.random}"
    }
    session.headers.update(headers)
    # test request to api
    response = session.get(test_api_url)
    log('s' if response.ok else 'e', f"API GET status - {response.status_code}")
    # retry if 401 (unauthorized)
    attempts = 0
    while response.status_code == 401 and attempts < 10:
        attempts += 1
        # update user agent and cookies
        headers["User-Agent"] = ua.random
        session = requests.Session()
        session.headers.update(headers)
        log('i', f"Retrying with different headers...")

        response = session.get(test_api_url)
        log('s' if response.ok else 'e', f"API GET status - {response.status_code}")
    if attempts == 10:
        log('e', "Reached max retries! Request failed...")
        return 1
    else:
        log('s', "Successfully updated session!")
        return 0

def init_session() -> None:
    global session

    err_code = update_session()
    if err_code > 0:
        log('e', "API unaccessible - aborting...")
        exit(3)
    return

def gen_resolutions_kbmarkup(resolutions: list) -> InlineKeyboardMarkup:#
    # init markup
    markup = InlineKeyboardMarkup()
    markup.row_width = 3
    # fill InlineKeyboardButtons list
    buttons = []
    for n in range(len(resolutions)):
        buttons.append(
            InlineKeyboardButton(
                # button text is only height instead of full resolution
                text=f"{resolutions[n].split('x')[1]}p", callback_data=resolutions[n]
            )
        )
    # add buttons to markup
    markup.add(*buttons)
    return markup

def is_valid_link(link: str) -> bool:
    # check if contains rutube.ru
    # log('i', f"Checking '{link}'...")
    if "rutube.ru" not in link:
        rdl.elog("Not a rutube.ru link!")
        return False
    # try to ping it
    try:
        test = session.get(link)
        if test.ok:
            return True
        elif test.status_code == 401:
            rdl.elog(f"Status is {test.status_code}. Updating session...")
            err_code = update_session()
            if err_code > 0:
                return False
            else:
                return True
        else:
            rdl.elog(f"Status not ok ({test.status_code})")
            return False
    except Exception as e:
        rdl.elog(f"Link is invalid: {e}")
        return False

def get_vinfo(link: str) -> tuple((any, int)):
    rdl.log(f"Getting vinfo for '{link}'...")
    # get video id
    vid = rdl.get_video_id(link)
    # get api url
    api_url = rdl.get_api_url(vid)
    # get video info
    vinfo, err_code = rdl.get_video_json(api_url)
    if err_code > 0:
        return (None, err_code)
    return (vinfo, 0)

def get_video_streams(vinfo: str) -> tuple((list, int)):
    rdl.log("Getting streams...")
    # get master playlist url
    master_url = rdl.get_master_playlist(vinfo)
    # get video title
    vtitle = rdl.get_vinfo_field(vinfo, "title")
    rdl.log(f"Title: '{vtitle}'")
    # get streams
    streams, err_code = rdl.get_available_streams(master_url)
    if err_code > 0:
        return (None, err_code)
    # set title for every stream
    for stream in streams:
        stream["title"] = vtitle
    
    return (streams, 0)

def get_video_resolutions(streams: list) -> tuple((list, int)):
    # init resolutions list
    resolutions = []
    for stream in streams:
        # get resolution height and append to list
        resolutions.append(stream["resolution"])
    
    return (resolutions, 0)

def get_video_properties(path: str) -> any:
    try:
        probe = ffmpeg.probe(path)
        return probe
    except Exception as e:
        rdl.elog(f"Can not get video properties: {e}")
        return None

### LOCAL HANDLING THREADS

req_urls = {}
req_streams = {}
req_queue = []
dl_queue = []
def req_queue_handler() -> None:
    global dl_queue, req_queue, req_urls

    log('o', 'Started request queue handler thread')
    while True:
        # wait
        time.sleep(0.25)

        # handle requests queue
        while len(req_queue) > 0:
            # get user id and provided link
            uid, link = req_queue[0]
            # start collecting info
            cur_mes = bot.send_message(uid, "Получение информации о видео...")
            
            # get vinfo
            vinfo, err_code = get_vinfo(link)
            if err_code > 0:
                bot.edit_message_text(
                    "Не удалось получить информацию о видео! Попробуйте другую ссылку...",
                    uid, cur_mes.id)
                req_queue.pop(0)
                continue

            # get streams
            streams, err_code = get_video_streams(vinfo)
            # can not get streams
            if err_code > 0:
                bot.edit_message_text(
                    "Не удалось получить информацию о видео! Попробуйте другую ссылку...",
                    uid, cur_mes.id)
                req_queue.pop(0)
                continue
            # log('i', "Got streams")
            req_streams[uid] = streams

            # get thumbnail
            os.mkdir(f"{uid}")
            err_code = rdl.download_thumbnail(vinfo, f"{uid}/thumbnail.jpg")
            if err_code > 0:
                bot.edit_message_text(
                    "Не удалось получить информацию о видео! Попробуйте другую ссылку...",
                    uid, cur_mes.id)
                req_queue.pop(0)
                continue

            # get resolutions
            resolutions, err_code = get_video_resolutions(streams)
            # can not get resolutions
            if err_code > 0:
                bot.edit_message_text(
                    "Не удалось получить информацию о видео! Попробуйте другую ссылку...",
                    uid, cur_mes.id)
                req_queue.pop(0)
                continue
            else:
                # log('i', "Got resolutions")
                bot.delete_message(uid, cur_mes.id)
                bot.send_photo(
                    uid, 
                    photo=open(f"{uid}/thumbnail.jpg", 'rb'),
                    caption=f"{streams[0]["title"]}\n\nВыберите качество для скачивания:",
                    reply_markup=gen_resolutions_kbmarkup(resolutions))
            # clean up
            os.remove(f"{uid}/thumbnail.jpg")
            os.rmdir(f"{uid}")
            # remove from queue
            req_queue.pop(0)
    return

def dl_queue_handler() -> None:
    global dl_queue, req_queue, req_urls

    log('o', 'Started download queue handler thread')
    while True:
        # wait
        time.sleep(0.25)

        # handle download queue
        while len(dl_queue) > 0:
            # get user id and provided link
            uid, stream = dl_queue[0]
            # create user directory to save video
            os.mkdir(f"{uid}")
            # download thumbnail
            vinfo, _ = get_vinfo(req_urls[uid])
            rdl.download_thumbnail(vinfo, f"{uid}/thumbnail.jpg")
            # download stream
            vpath = f"{uid}/{stream["title"]}"
            err_code = rdl.download_stream(stream, vpath)
            if err_code > 0:
                log('e', "Can not download stream!")
                bot.send_message(uid, "Не удалось скачать видео! Попробуйте позже или запросите другое видео...")
                dl_queue.pop(0)
                continue
            log('s', f"Downloaded video for {uid}. Sending...")
            # get video properties
            vprop = get_video_properties(f"{vpath}.mp4")
            if vprop == None:
                bot.send_message(uid, "Что-то пошло не так...")
                dl_queue.pop(0)
                continue
            vwidth = int(stream["resolution"].split('x')[0])
            vheight = int(stream["resolution"].split('x')[1])
            # send video to user
            bot.send_video(uid,
            video=open(f"{vpath}.mp4", 'rb'),
            duration=vprop["format"]["duration"],
            width=vwidth,
            height=vheight,
            thumbnail=open(f"{uid}/thumbnail.jpg", 'rb'),
            caption=f"{stream["title"]}",
            timeout=10000,
            supports_streaming=True)
            log('s', f"Sent video to {uid}")
            # remove video and user directory
            os.remove(f"{vpath}.mp4")
            os.remove(f"{uid}/thumbnail.jpg")
            os.rmdir(f"{uid}")
            rdl.log("Cleaned up user directory")
            # remove from queue
            dl_queue.pop(0)

    return

### BOT COMMANDS

# start
text_welcome: str = "Привет, я бот для скачивания видео с рутуба (rutube.ru)!\n\nЧтобы скачать видео, отправь мне ссылку на него и я предложу варианты для скачивания!"
@bot.message_handler(commands=["start"])
def bot_start(message) -> None:
    bot.send_message(message.chat.id, text_welcome)
    return

# text message (not command)
@bot.message_handler(func=lambda link_handler: True)
def bot_cmd_message(message) -> None:
    global dl_queue, req_queue, req_urls
    uid = message.chat.id

    # check link
    link: str = message.text
    if not is_valid_link(link):
        bot.send_message(uid, "Неправильная ссылка!")
        return
    # check if user already requested video download
    for req in dl_queue:
        if req[0] == uid:
            log('w', f"{uid} already has requested video")
            bot.send_message(uid, "Дождитесь загрузки текущего видео!")
            return
    # update user url and add user to queue
    log('i', f"{uid} requested '{link}'")
    req_urls[uid] = link
    req_queue.append((uid, link))
    return

@bot.callback_query_handler(func=lambda call: True)
def bot_callback_handler(call) -> None:
    rdl.log(f"Selected '{call.data}'")
    uid = call.message.chat.id

    for stream in req_streams[uid]:
        if stream["resolution"] == call.data:
            dl_queue.append((uid, stream))
            bot.answer_callback_query(call.id)
            bot.delete_message(uid, call.message.id)
            bot.send_message(uid, f"Ваше видео {len(dl_queue)} в очереди, ожидайте загрузки...")
            return

    bot.answer_callback_query(call.id)
    bot.delete_message(uid, call.message.id)
    log('e', f"Can not find url corresponding to selected resolution! ({call.data})")
    bot.send_message(uid, "Не удалось скачать видео! Попробуйте другую ссылку")
    return

rdl.init_log_levels(True, True, False, False, False)
# init requests session
init_session()

# start request queue handler thread
req_queue_handler_thread = threading.Thread(target=req_queue_handler)
req_queue_handler_thread.daemon = True
req_queue_handler_thread.start()

# start download queue handler thread
dl_queue_handler_thread = threading.Thread(target=dl_queue_handler)
dl_queue_handler_thread.daemon = True
dl_queue_handler_thread.start()

# start polling
log('s', "Bot launched successfully")
bot.polling(timeout=10, long_polling_timeout=20)

# bot stopped
log('i', "Bot stopped")