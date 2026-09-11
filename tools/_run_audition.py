import sys
import _dev_ssh as d
c = d.connect(); sftp = c.open_sftp()
sftp.put("_dev_voice_audition.py", "/tmp/_dev_voice_audition.py"); sftp.close()
o, e = d.run(c, "cd /root/isora && python3 /tmp/_dev_voice_audition.py " +
             " ".join(sys.argv[1:]), 300)
print(((o or "") + (e or "")).encode("ascii", "replace").decode())
c.close()
