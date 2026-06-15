from ultralytics import YOLO

model = YOLO("yolov8n.yaml")

def on_train_epoch_end(trainer):
    print("KEYS:", dir(trainer))
    print("TLOSS:", getattr(trainer, 'tloss', None))
    print("METRICS:", getattr(trainer, 'metrics', None))

model.add_callback("on_train_epoch_end", on_train_epoch_end)
model.train(data="coco8.yaml", epochs=1, imgsz=32, batch=2, device='cpu')
