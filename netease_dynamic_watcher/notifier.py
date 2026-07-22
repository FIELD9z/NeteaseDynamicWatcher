class PushNotifier:
    def __init__(self, sender):
        self.sender = sender

    def notify(self, event):
        return self.sender(event.notification_title(), event.notification_body())


class NullNotifier:
    def notify(self, event):
        return True
