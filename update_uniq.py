import time
import sys
import MySQLdb
import configparser
import traceback

Config = configparser.ConfigParser()
Config.read(sys.argv[1])

def get_dbcon():
  db = MySQLdb.connect(host=Config.get('Database', 'Host'), user=Config.get('Database', 'User'), passwd=Config.get('Database', 'Password'), db=Config.get('Database', 'Database'), charset='utf8')
  cur = db.cursor()
  cur.execute('SET NAMES utf8mb4')
  return db, cur

def add_new_chats(db, cur):
  cur.execute("INSERT INTO chat_uniqueness(convid) SELECT DISTINCT convid FROM chat_counters WHERE sent=0 AND message_count >= 100 AND convid NOT IN (SELECT convid FROM chat_uniqueness)")
  db.commit()
  if cur.rowcount > 0:
    print("Added %d new chats" % cur.rowcount)

get_chats_q = """
SELECT * FROM (
  SELECT convid, message_count, new_messages, age, CAST((100 * new_messages)/(100+message_count) + age / (1440 * 7)  AS DOUBLE) AS score, COALESCE(uniqueness, -1) AS uniqueness, chatname
  FROM (
    SELECT convid, message_count, message_count - last_count AS new_messages, TIMESTAMPDIFF(MINUTE, last_update, CURRENT_TIMESTAMP) AS age, uniqueness, long_name as chatname
    FROM chat_uniqueness LEFT JOIN chat_counters USING (convid) LEFT JOIN chatinfo_current USING (convid) LEFT JOIN chatinfo_v USING (chatinfo_id) WHERE sent=0
  ) a
) b WHERE score > 0.1 OR uniqueness < 0 ORDER BY score DESC LIMIT 10;
"""

varsleep = 450

def update_step(db, cur):
  global varsleep
  starttime = time.time()
  add_new_chats(db, cur)
  cur.execute(get_chats_q)
  chats_to_update = list(cur.fetchall())
  if not chats_to_update:
    print("No chats to update")
    return 60
  for i in chats_to_update:
    print("Chat: %16d New: %6d / %6d updated: %6d minutes ago score: %4.2f uniq: %.3f %s" % i)
  convid = chats_to_update[0][0]
  chatname = chats_to_update[0][6]
  print("Updating stats for %d %s" % (convid, chatname))
  cur.execute("SELECT COALESCE(SUM(IF(count=1, 1, 0)) / COUNT(*), 0) FROM chat LEFT JOIN chat_hashcounts ON hash=UNHEX(SHA2(text, 256)) "
    "WHERE chat.sent = 0 AND chat.convid=%s AND text NOT IN (SELECT DISTINCT emoji FROM stickers)", (convid,))
  uniqueness = cur.fetchone()[0]
  cur.execute("SELECT message_count FROM chat_counters WHERE convid = %s AND sent = 0", (convid,))
  msgcount = cur.fetchone()[0]
  cur.execute("SELECT COUNT(*) FROM chat WHERE sent=0 AND convid=%s AND text NOT IN (SELECT DISTINCT emoji FROM stickers)", (convid,))
  msgcount_v = cur.fetchone()[0]
  db.commit()
  #print("Updated uniqueness of chat %s from %.3f to %.3f count=%d countv=%d" % (chatname, chats_to_update[0][5], uniqueness, msgcount, msgcount_v))
  cur.execute("UPDATE chat_uniqueness SET "
    "uniqueness=%s, "
    "last_count=%s, "
    "last_count_valid=%s, "
    "last_update = CURRENT_TIMESTAMP "
    "WHERE convid=%s", (uniqueness, msgcount, msgcount_v, convid))
  db.commit()
  endtime = time.time()
  elaps = endtime-starttime
  score = chats_to_update[0][4]
  if score < 0.9:
    varsleep = varsleep + 1
  if score > 1.1 and varsleep > 10:
    varsleep = varsleep - 1
  sleeptime = (elaps * 10 + varsleep) / max(0.25, chats_to_update[0][4])
  #print("Done updating stats for %d %s (took %.3f) (sleeping for %6.3f)" % (convid, chatname, elaps, sleeptime))
  print("Updated %s from %.3f to %.3f (%.6f) cnt=%d/%d score %.3f took %.3f slp %6.3f" %
       (chatname, chats_to_update[0][5], uniqueness, float(uniqueness) - chats_to_update[0][5], msgcount_v, msgcount, chats_to_update[0][4], elaps, sleeptime))
  return sleeptime

while True:
  try:
    db, cur = get_dbcon()
    slp = update_step(db, cur)
    time.sleep(slp)
  except:
    traceback.print_exc()
    time.sleep(30)
  finally:
    db.close()
