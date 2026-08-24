# -*- coding: utf-8 -*-
"""
نقطة التشغيل الرئيسية: بتشغّل البوت ولوحة التحكم عبر الويب مع بعض بنفس العملية.
هاد هو الملف يلي لازم تحطه بأمر التشغيل (Start Command) على Railway: python main.py
"""
import threading
import logging

import db
import bot
import admin_web

logger = logging.getLogger(__name__)


def main():
    db.init_db()

    web_thread = threading.Thread(target=admin_web.run_web, daemon=True)
    web_thread.start()
    logger.info("لوحة التحكم عبر الويب شغّالة بخيط منفصل...")

    # البوت بيشتغل بالخيط الرئيسي (استدعاء يحجز - blocking)
    bot.run_bot()


if __name__ == "__main__":
    main()
