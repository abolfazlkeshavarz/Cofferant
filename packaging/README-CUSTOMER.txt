COFFERANT — installation guide
================================

What you need
-------------
* a server with Ubuntu or Debian (1 CPU, 1 GB RAM is enough), ports 80 and 443 open, root access
* a domain whose DNS "A" record points to that server's IP address
* the license key you received (CFR-XXXX-XXXX-XXXX-XXXX)
* an email address (certificate expiry warnings)

Install (about 5 minutes)
-------------------------
    tar xzf cofferant-customer-<version>.tar.gz
    cd cofferant-customer-<version>
    sudo ./install.sh

The installer asks for your domain, email and license key, installs Docker if needed, loads the
application, gets a free HTTPS certificate and starts everything. At the end it prints the admin
username and password for your panel. Open  https://YOUR-DOMAIN/users/login/  and change the password in
Settings.

Everyday commands (run inside this folder)
------------------------------------------
    make health                      check that everything works
    make logs                        see what the application is doing
    make backup                      take a backup now (automatic backups also run every 12 hours)
    make backups-list                list the backups kept on the server
    make restore-latest              restore the newest backup (replaces current data!)
    make backup-remote-setup REMOTE=user@other-server:/backups/cofferant
                                     also copy every backup to a second server (strongly recommended)
    make admin-password              set a new admin password
    make change-domain DOMAIN=new.example.com    move to another domain

Updating
--------
You will receive a new file  cofferant-images.tar.gz  for each new version:

    make update FILE=/path/to/cofferant-images.tar.gz

It takes a backup first, then installs the new version. Your data is kept.

License
-------
The panel checks your license automatically. If the subscription ends or is cancelled, the admin panel and
online ordering are locked, and people who scan your QR codes are shown a page asking them to contact
the coffee shop. Everything returns within seconds after the subscription is renewed. If this server
cannot reach the license server, everything keeps working for 72 hours.

Important
---------
* Keep a copy of the file  .env  somewhere safe (it holds your secret keys).
* Do not delete the Docker volumes (cofferant_data, cofferant_media): they hold your data.

--------------------------------------------------------------------------------------------------------
راهنمای نصب کافیرانت (خلاصه)
-----------------------------
۱) سرور اوبونتو/دبیان با دسترسی root و پورت‌های ۸۰ و ۴۴۳ باز، و دامنه‌ای که رکورد A آن به آی‌پی سرور اشاره کند.
۲) پوشه را باز کنید و بزنید:   sudo ./install.sh
۳) دامنه، ایمیل و کلید لایسنس را وارد کنید. در پایان نام کاربری و رمز مدیر چاپ می‌شود.
۴) ورود به پنل:   https://دامنه-شما/users/login/   (رمز را از «تنظیمات» عوض کنید)
۵) پشتیبان‌گیری خودکار هر ۱۲ ساعت انجام می‌شود؛ برای امنیت بیشتر یک سرور دوم هم تعریف کنید:
      make backup-remote-setup REMOTE=user@other-server:/backups/cofferant
۶) به‌روزرسانی:   make update FILE=/path/to/cofferant-images.tar.gz
۷) اگر اشتراک تمام یا لغو شود، پنل مدیریت قفل می‌شود و مشتریانی که QR را اسکن می‌کنند به صفحه «تماس با کافه»
   می‌روند؛ با تمدید ظرف چند ثانیه دوباره فعال می‌گردد. اگر سرور به سرور لایسنس دسترسی نداشته باشد، تا ۷۲ ساعت همه‌چیز کار می‌کند.
۸) فایل .env را در جای امن نگه دارید و حجم‌های داکر (cofferant_data و cofferant_media) را پاک نکنید.
