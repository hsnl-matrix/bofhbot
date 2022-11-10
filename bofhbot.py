#!/usr/bin/python3 -u

import mastodon, os, sys, datetime, time, asyncio, nio, requests, configparser, html2text, re
from pprint import pprint as p

CLIENTCRED_FILE = 'bofhbot_clientcred.secret'
USERCRED_FILE = 'bofhbot_usercred.secret'
MATRIX_TOKEN_FILE = 'bofhbot_matrix_tokens.secret'
MATRIX_NIO_STORE = 'bofhbot_matrix_store.secret/'
SCOPES = ['read:statuses', 'write:statuses', 'read:accounts', 'write:conversations']

tooter = None
matrix = None
me = None

def mastodon_login():
  global tooter

  print('==[MASTODON LOGIN]==')
  print('Open this URL in your browser:\n')
  print(tooter.auth_request_url(scopes = SCOPES))
  print('\nPaste the authorization code here:')
  try:
    auth_code = input('🔐 > ')
  except (KeyboardInterrupt, EOFError) as e:
    print('\nBye!')
    sys.exit()
  print()
  tooter.log_in(code = auth_code, scopes = SCOPES, to_file = USERCRED_FILE)

def mastodon_init():
  global tooter, me

  if not os.path.exists(CLIENTCRED_FILE):
    print('==[MASTODON SETUP]==')
    print('What is the address of your Mastodon(-compatible) instance?')
    try:
      api_base_url = f"https://{input('🌐 > https://')}"
    except (KeyboardInterrupt, EOFError) as e:
      print('\nBye!')
      sys.exit()
    print()

    mastodon.Mastodon.create_app('BOFH Bot', scopes = SCOPES, api_base_url = api_base_url, to_file = CLIENTCRED_FILE)

  tooter = mastodon.Mastodon(
    client_id = CLIENTCRED_FILE,
    access_token = USERCRED_FILE,
    feature_set = 'pleroma',         # 'pleroma' because that enables content-type, which glitch-soc also supports
    request_timeout = 5              # default is 300 seconds (5 minutes) which is insane and useless
  )

  if not os.path.exists(USERCRED_FILE):
    mastodon_login()

  while me is None:
    try:
      me = tooter.me()
    except mastodon.MastodonUnauthorizedError as e:
      print(f'That did not go very well:\n{e.args[0]} {e.args[1]}: {e.args[2]}, {e.args[3]}.\nLet\'s try to login again, shall we?')
      mastodon_login()

async def matrix_init():
  global matrix

  matrix_secrets = configparser.ConfigParser()
  if not os.path.isdir(MATRIX_NIO_STORE):
    os.mkdir(MATRIX_NIO_STORE)

  if os.path.exists(MATRIX_TOKEN_FILE):
    matrix_secrets.read(MATRIX_TOKEN_FILE)

    matrix = nio.AsyncClient(matrix_secrets['matrix']['homeserver_url'], matrix_secrets['matrix']['mxid'], store_path = MATRIX_NIO_STORE)

    matrix.restore_login(
      user_id      = matrix_secrets['matrix']['mxid'],
      device_id    = matrix_secrets['matrix']['device_id'],
      access_token = matrix_secrets['matrix']['access_token']
    )

  else:
    print('==[MATRIX LOGIN]==')
    print('Enter the bots MXID (@user:example.tld):')
    try:
      mxid = input('👤 > ')
    except (KeyboardInterrupt, EOFError) as e:
      print('\nBye!')
      sys.exit()

    if mxid[0] != '@':
      mxid = '@' + mxid
      print("You forgot the @! Don't worry, I fixed it for you.")

    # assuming everyone implements .well-known/matrix for now
    try:
      host = mxid.split(':')[1]
      homeserver_url = requests.get(f"https://{host}/.well-known/matrix/client").json()['m.homeserver']['base_url']
    except requests.exceptions.ConnectionError:
      print(f"\nCould not find homeserver at {host}")
      sys.exit(42)
    print(f"\nFound homeserver at {homeserver_url.split('//')[1]}\n")

    print('Enter the bots password:')
    try:
      password = input('🔐 > ')
    except (KeyboardInterrupt, EOFError) as e:
      print('\nBye!')
      sys.exit()
    print()

    matrix = nio.AsyncClient(homeserver_url, mxid, store_path = MATRIX_NIO_STORE)
    await matrix.login(password, device_name = "BOFH Bot")

    matrix_secrets['matrix'] = {}
    matrix_secrets['matrix']['mxid'] = mxid
    matrix_secrets['matrix']['homeserver_url'] = homeserver_url
    matrix_secrets['matrix']['access_token'] = matrix.access_token
    matrix_secrets['matrix']['device_id'] = matrix.device_id

    with open(MATRIX_TOKEN_FILE, 'w') as f:
      matrix_secrets.write(f)

  asyncio.create_task(matrix.sync_forever(5000, full_state=True))

  await matrix.synced.wait()

  matrix.add_event_callback(cb_autojoin_room, nio.InviteEvent)
  matrix.add_event_callback(cb_incoming_message, nio.RoomMessageText)


async def cb_autojoin_room(room: nio.MatrixRoom, event: nio.InviteEvent):
  global matrix

  for r in (await matrix.joined_rooms()).rooms:
    if r != room.room_id:
      print(f"Leaving room {r}")
      await matrix.room_leave(r)

  print(f"Joining room {room.name} ({room.room_id})")
  await matrix.join(room.room_id)
  await matrix.synced.wait()
  await say_hello()

async def cb_incoming_message(room: nio.MatrixRoom, event: nio.RoomMessageText):
  global matrix, tooter

  feedback = "❓️"

  for needle in [f"{tooter.api_base_url}/web/statuses/", matrix.user_id, 'Recieved message from']:
    for haystack in [event.body, event.formatted_body]:
      if needle not in haystack:
        return

  print(f"[{datetime.datetime.now()}] 💬 => 🦣 ({event.sender}) => ", end='')

  try:
    status_id_match = re.search(f"{tooter.api_base_url}/web/statuses/([0-9]+)", event.formatted_body)
    if not status_id_match:
      return

    status_id = status_id_match.group(1)
    orig_toot = tooter.status(status_id)

    print(f"[{orig_toot.account.display_name}] ({orig_toot.account.acct})")

    reply_text = event.formatted_body.split('</mx-reply>')[1]
    reply_text += f"<p style='text-align: right;'><em>-- {(await matrix.get_displayname(event.sender)).displayname}</em></p>"

    tooter.status_reply(orig_toot, reply_text, content_type = 'text/html')
    feedback = "✅"

  except Exception as e:
    feedback = "❌"
    print(f"{e.args[0]} {e.args[1]}: {e.args[2]}, {e.args[3]}")

  finally:
    rooms = (await matrix.joined_rooms()).rooms
    if rooms and (rooms == list(matrix.rooms)):
        await matrix.room_send(
          room_id = rooms[0],
          ignore_unverified_devices = True,
          message_type = "m.reaction",
          content = {
            "m.relates_to": {
              "rel_type": "m.annotation",
              "event_id": event.event_id,
              "key": feedback,
            },
          },
        )

async def say_hello():
  global matrix, me
  rooms = (await matrix.joined_rooms()).rooms
  if rooms:
    if rooms == list(matrix.rooms):
      print(f"I'm in {len(rooms)} room(s): {rooms}")
      await matrix.room_send(
        room_id = rooms[0],
        ignore_unverified_devices = True,
        message_type = "m.room.message",
        content = {
          "msgtype": "m.notice",
          "body": f"Listening as {me.url}",
          "format": "org.matrix.custom.html",
          "formatted_body": f"Listening as 🦣[<a href='{me.url}'>{me.display_name}</a>]",
        },
      )
    else:
      print(f"Room join weirdness in progress: {rooms} vs {list(matrix.rooms)}")
  else:
    print(f"Help, I'm not in any room, invite me!")
    print(f"/invite {matrix.user_id}")

async def main() -> None:
  global tooter, matrix, me
  os.umask(0o077) # strict file permissions make sense for our *.secret stuff

  try:
    mastodon_init()
    await matrix_init()

    print(f'Hello, 🦣[{me.display_name}] 💬[{(await matrix.get_displayname()).displayname}]')
    await say_hello()

    while True:
      if matrix.rooms:
        for conversation in tooter.conversations():
          if conversation.unread:
            print(f"[{datetime.datetime.now()}] 🦣 => 💬 [{conversation.last_status.account.display_name}] ({conversation.last_status.account.acct})")

            body_text = f"Recieved message from [{conversation.last_status.account.display_name}] "
            body_html = f"Recieved message from [{conversation.last_status.account.display_name}] "

            body_text += f"({conversation.last_status.account.acct})\n\n"
            body_html += f"(<a href='{conversation.last_status.account.url}'>{conversation.last_status.account.acct}</a>)"

            if conversation.last_status.spoiler_text:
              body_text += f"CW: {conversation.last_status.spoiler_text}\n\n"
              body_html += f"<br><span data-mx-spoiler='{conversation.last_status.spoiler_text}'>"

            body_text += html2text.html2text(conversation.last_status.content)
            body_html += f"<blockquote>{conversation.last_status.content}</blockquote>"

            if conversation.last_status.media_attachments:
              body_text +="Attachments:\n"
              body_html +="<p>Attachments:<ul>"

              for media in conversation.last_status.media_attachments:
                body_text += f" - {media.description or 'no description'} ({media.type}"
                body_html += f"<li><a href='{media.url}'>{media.description or 'no description'}</a> ({media.type}"

                if not False in (i in media.meta.original for i in ('width', 'height')):
                  body_text += f", {media.meta.original.width}×{media.meta.original.height}"
                  body_html += f", {media.meta.original.width}×{media.meta.original.height}"
                if 'duration' in media.meta.original:
                  body_text += f", {datetime.timedelta(seconds=round(media.meta.original.duration))}"
                  body_html += f", {datetime.timedelta(seconds=round(media.meta.original.duration))}"

                body_text += f")\n   {media.url}\n"
                body_html +=")</le>"
              body_text +="\n"
              body_html +="</ul>"

            if conversation.last_status.spoiler_text:
              body_html += f"</span>"

            message_url = f"{tooter.api_base_url}/web/statuses/{conversation.last_status.id}"
            body_text += f"Original message: {message_url}"
            body_html += f"<a href='{message_url}'>Original message</a>"

            rooms = (await matrix.joined_rooms()).rooms
            if rooms and (rooms == list(matrix.rooms)):
              await matrix.room_send(
                room_id=(await matrix.joined_rooms()).rooms[0],
                ignore_unverified_devices = True,
                message_type="m.room.message",
                content={
                  "msgtype": "m.notice",
                  "format": "org.matrix.custom.html",
                  "body": body_text,
                  "formatted_body": body_html,
                },
              )
              tooter.conversations_read(conversation.id)
      await asyncio.sleep(5)
  except KeyboardInterrupt:
    await matrix.close()

if __name__ == "__main__":
  asyncio.run(main())
