from app.services.line_service import send_line_message_async


def notify_alert(camera_id, camera_name, room_name, detection_type, timestamp, image_path,
                 confidence=None, notification_id=None, wait=False):
    """Single entry point for every outbound alert channel (currently LINE). Every detection loop calls this
    instead of a channel's sender directly, so a channel is added or removed here and nowhere else.

    The wording never asserts that a fall happened: the model's score cannot tell a fall from a deep bend, so a
    fall alert asks a person to look (see line_service). Escalation and "still down" belong to a later step.

    notification_id only reaches LINE: it is what the "รับทราบ" button posts back, so the webhook can mark that
    exact alert acknowledged. Without `wait` the send runs on its own thread, so a slow LINE API can never stall
    frame processing; with `wait=True` it returns how many targets the alert reached.
    """
    return send_line_message_async(camera_id, camera_name, room_name, detection_type, timestamp, image_path,
                                   confidence=confidence, notification_id=notification_id, wait=wait)
