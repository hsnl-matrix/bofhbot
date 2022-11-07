#!/usr/bin/python3

import mastodon, os, sys, datetime, time
from pprint import pprint as p

CLIENTCRED_FILE = 'bofhbot_clientcred.secret'
USERCRED_FILE = 'bofhbot_usercred.secret'
SCOPES = ['read:statuses', 'write:statuses', 'read:accounts', 'write:conversations']
# ~ SCOPES = ['read:statuses', 'write:statuses', 'push']

def login():
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

def listener_callback(e):
  print(datetime.datetime.now())
  p(e)


if not os.path.exists(CLIENTCRED_FILE):
  mastodon.Mastodon.create_app('BOFH Bot', scopes = SCOPES, api_base_url = 'https://hsnl.social', to_file = CLIENTCRED_FILE)

tooter = mastodon.Mastodon(client_id = CLIENTCRED_FILE, access_token = USERCRED_FILE)

if not os.path.exists(USERCRED_FILE):
  login()

me = None
while me is None:
  try:
    me = tooter.me()
  except mastodon.MastodonUnauthorizedError as e:
    print(f'That did not go very well.\n{e.args[0]} {e.args[1]}: {e.args[2]}, {e.args[3]}.\nLet\'s try to login again, shall we?')
    login()

print(f'Hello, {me.display_name}.')

while True:
  for conversation in tooter.conversations():
    if conversation.unread:
      print(f'Recieved message at {datetime.datetime.now} from "{conversation.last_status.account.display_name}" [{conversation.last_status.url}]: {conversation.last_status.content}')
      tooter.status_reply(conversation.last_status, 'Canned reply for testing purposes (with *italic* and **bold** even)')
      tooter.conversations_read(conversation.id)
  time.sleep(5)

