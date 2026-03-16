from ultralytics import YOLO
def train_model():
    
    model = YOLO('yolo11m-custom.pt')

    model.train(
        data='custom_dataset.yaml', 
        imgsz=640, 
        device='0', 
        batch=16, 
        epochs=100,             
        workers=10,
        name='trained-results-v2',
        patience=25,            # Stop if no improvement for 25 epochs
        lr0=0.005,              # Set a custom learning rate
        fliplr=0.5,             # 50% chance of horizontal flip
        degrees=15,              # Add random rotation
        resume=False            # Resume training from last checkpoint
    )


if __name__ == '__main__':
    # freeze_support() # Add if creating an executable
    train_model() # Call the function to start training