def send_telegram_message_async(camera_id, camera_name, room_name, detection_type, timestamp, image_path):
    def _send():
        from app import create_app
        app = create_app()

        with app.app_context():
            camera = Camera.query.get(camera_id)
            if not camera:
                return

            now = datetime.now(tz)

            # ✅ บังคับ risk level
            if "fall" in detection_type:
                risk_level = "red"
            elif "alone" in detection_type:
                risk_level = "yellow"
            else:
                risk_level = "normal"

            # ✅ Alert style
            if risk_level == "red":
                alert_title = "🚨 CRITICAL ALERT 🚨"
                priority_text = "HIGH PRIORITY ALERT"
                event_text = "🚨 FALL DETECTED - IMMEDIATE ASSISTANCE REQUIRED!"
                emoji = "🔴"

            elif risk_level == "yellow":
                alert_title = "⚠️ WARNING ALERT ⚠️"
                priority_text = "MEDIUM PRIORITY ALERT"
                event_text = "👤 Person Alone - Monitoring Required"
                emoji = "🟡"

            else:
                alert_title = "ℹ️ STATUS UPDATE ℹ️"
                priority_text = "INFORMATION"
                event_text = "Normal Activity"
                emoji = "🟢"

            # ✅ ข้อความ format ตามที่คุณต้องการ
            text = (
                f"{alert_title}\n"
                f"{priority_text}\n\n"
                f"📹 Camera: {camera_name}\n"
                f"🏠 Room: {room_name}\n"
                f"📋 Event: {event_text}\n"
                f"⚠️ Risk Level: {risk_level.upper()}\n"
                f"🕐 Time: {now.strftime('%Y-%m-%d %H:%M:%S (GMT+7)')}\n\n"
                f"Please check the camera feed immediately for more details."
            )

            settings = TelegramSettings.get_settings(camera.user_id)
            if not settings or not settings.bot_token or not settings.chat_id:
                print("[Telegram] Missing bot_token or chat_id")
                return

            bot_token = settings.bot_token
            chat_id = settings.chat_id

            try:
                # 📲 ส่งข้อความ
                msg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                requests.post(msg_url, data={
                    'chat_id': chat_id,
                    'text': text
                }, timeout=10)

                # 📸 ส่งรูป (ถ้ามี)
                if image_path and os.path.exists(image_path):
                    photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

                    with open(image_path, 'rb') as img:
                        requests.post(photo_url, data={
                            'chat_id': chat_id,
                            'caption': f"{emoji} {event_text}"
                        }, files={'photo': img}, timeout=15)

                    print(f"[Camera {camera_id}] ✅ Image sent")

                else:
                    print(f"[Camera {camera_id}] ❌ No image found")

            except Exception as e:
                print(f"[Camera {camera_id}] Telegram error: {e}")

    Thread(target=_send).start()