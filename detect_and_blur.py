#Object Crop Using YOLOv7
import argparse
import configparser
import time
from pathlib import Path
import os
import cv2
import torch
import torch.backends.cudnn as cudnn
from numpy import random

from models.experimental import attempt_load
from utils.datasets import LoadStreams, LoadImages
from utils.general import check_img_size, check_requirements, check_imshow, non_max_suppression, apply_classifier, \
    scale_coords, xyxy2xywh, strip_optimizer, set_logging, increment_path
from utils.plots import plot_one_box
from utils.torch_utils import select_device, load_classifier, time_synchronized, TracedModel
from utils.lock import lock_script


def detect(save_img=False):
    source, weights, view_img, save_txt, imgsz, trace, blurratio, hidedetarea, save_org = opt.source, opt.weights, opt.view_img, opt.save_txt, opt.img_size, not opt.no_trace, opt.blurratio, opt.hidedetarea, opt.save_org
    save_img = not opt.nosave and not source.endswith('.txt')  # save inference images
    webcam = source.isnumeric() or source.endswith('.txt') or source.lower().startswith(
        ('rtsp://', 'rtmp://', 'http://', 'https://'))

    # Directories
    save_dir = Path(increment_path(opt.dest, increment_dest=opt.increment_dest))  # increment run
    (save_dir / 'labels' if save_txt else save_dir).mkdir(parents=True, exist_ok=True)  # make dir

    # Initialize
    set_logging()
    device = select_device(opt.device)
    half = device.type != 'cpu'  # half precision only supported on CUDA

    # Load model
    model = attempt_load(weights, map_location=device)  # load FP32 model
    stride = int(model.stride.max())  # model stride
    imgsz = check_img_size(imgsz, s=stride)  # check img_size

    if trace:
        model = TracedModel(model, device, imgsz)

    if half:
        model.half()  # to FP16

    # Second-stage classifier
    classify = False
    if classify:
        modelc = load_classifier(name='resnet101', n=2)  # initialize
        modelc.load_state_dict(torch.load('weights/resnet101.pt', map_location=device)['model']).to(device).eval()

    # Set Dataloader
    vid_path, vid_writer = None, None
    if webcam:
        view_img = check_imshow()
        cudnn.benchmark = True  # set True to speed up constant image size inference
        dataset = LoadStreams(source, img_size=imgsz, stride=stride)
    else:
        dataset = LoadImages(source, img_size=imgsz, stride=stride, limit=opt.limit, rotate=opt.rotate)

    # Get names and colors
    names = model.module.names if hasattr(model, 'module') else model.names
    colors = [[random.randint(0, 255) for _ in range(3)] for _ in names]

    # Run inference
    if device.type != 'cpu':
        model(torch.zeros(1, 3, imgsz, imgsz).to(device).type_as(next(model.parameters())))  # run once
    old_img_w = old_img_h = imgsz
    old_img_b = 1

    t0 = time.time()
    limiter = 0
    for path, img, im0s, vid_cap in dataset:
        limiter += 1
        if (limiter == opt.limit):
            print("Limit reached!")
            break

        img = torch.from_numpy(img).to(device)
        img = img.half() if half else img.float()  # uint8 to fp16/32
        img /= 255.0  # 0 - 255 to 0.0 - 1.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)

        # Warmup
        if device.type != 'cpu' and (old_img_b != img.shape[0] or old_img_h != img.shape[2] or old_img_w != img.shape[3]):
            old_img_b = img.shape[0]
            old_img_h = img.shape[2]
            old_img_w = img.shape[3]
            for i in range(3):
                model(img, augment=opt.augment)[0]

        # Inference
        t1 = time_synchronized()
        pred = model(img, augment=opt.augment)[0]
        t2 = time_synchronized()

        # Apply NMS
        pred = non_max_suppression(pred, opt.conf_thres, opt.iou_thres, classes=opt.classes, agnostic=opt.agnostic_nms)
        t3 = time_synchronized()

        # Apply Classifier
        if classify:
            pred = apply_classifier(pred, modelc, img, im0s)

        # Process detections
        for i, det in enumerate(pred):  # detections per image
            if webcam:  # batch_size >= 1
                p, s, im0, frame = path[i], '%g: ' % i, im0s[i].copy(), dataset.count
            else:
                p, s, im0, frame = path, '', im0s, getattr(dataset, 'frame', 0)

            p = Path(p)  # to Path
            save_path = str(save_dir / p.name)  # img.jpg
            txt_path = str(save_dir / 'labels' / p.stem) + ('' if dataset.mode == 'image' else f'_{frame}')  # img.txt
            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  # normalization gain whwh

            file_name, file_type = os.path.splitext(save_path)
            if (file_type == ".webp"):
                options = [int(cv2.IMWRITE_WEBP_QUALITY), opt.compression]
            elif  (file_type == ".jpg" or file_type == ".jpeg"):
                options = [cv2.IMWRITE_JPEG_QUALITY, opt.compression, cv2.IMWRITE_JPEG_OPTIMIZE, 1]
            else:
                options = []

            if len(det):
                # Rescale boxes from img_size to im0 size
                det[:, :4] = scale_coords(img.shape[2:], det[:, :4], im0.shape).round()

                # Print results
                for c in det[:, -1].unique():
                    n = (det[:, -1] == c).sum()  # detections per class
                    s += f"{n} {names[int(c)]}{'s' * (n > 1)}, "  # add to string

                if save_org and save_txt:
                    print(f"Saving original image to {txt_path}{file_type}");
                    cv2.imwrite(txt_path + file_type, im0, options)

                # Write results
                for *xyxy, conf, cls in reversed(det):
                    
                    if save_txt:  # Write to file
                        xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()  # normalized xywh
                        line = (cls, *xywh, conf) if opt.save_conf else (cls, *xywh)  # label format
                        with open(txt_path + '.txt', 'a') as f:
                            f.write(('%g ' * len(line)).rstrip() % line + '\n')

                    #Add Object Blurring Code
                    #..................................................................
                    if blurratio:
                        crop_obj = im0[int(xyxy[1]):int(xyxy[3]),int(xyxy[0]):int(xyxy[2])]
                        blur = cv2.blur(crop_obj,(blurratio,blurratio))
                        im0[int(xyxy[1]):int(xyxy[3]),int(xyxy[0]):int(xyxy[2])] = blur
                    #..................................................................
                    
                    if save_img or view_img:  # Add bbox to image
                        label = f'{names[int(cls)]} {conf:.2f}'
                        if not hidedetarea:
                            plot_one_box(xyxy, im0, label=label, color=colors[int(cls)], line_thickness=3)

            # Print time (inference + NMS)
            print(f'{s}Done. ({(1E3 * (t2 - t1)):.1f}ms) Inference, ({(1E3 * (t3 - t2)):.1f}ms) NMS')

            # Stream results
            if view_img:
                cv2.imshow(str(p), im0)
                cv2.waitKey(1)  # 1 millisecond

            # Save results (image with detections)
            if save_img:
                if dataset.mode == 'image':
                    cv2.imwrite(save_path, im0, options)
                    print(f" The image with the result is saved in: {save_path}")
                else:  # 'video' or 'stream'
                    if vid_path != save_path:  # new video
                        vid_path = save_path
                        if isinstance(vid_writer, cv2.VideoWriter):
                            vid_writer.release()  # release previous video writer
                        if vid_cap:  # video
                            fps = vid_cap.get(cv2.CAP_PROP_FPS)
                            w = int(vid_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                            h = int(vid_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        else:  # stream
                            fps, w, h = 30, im0.shape[1], im0.shape[0]
                            save_path += '.mp4'
                        vid_writer = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
                    vid_writer.write(im0)
            
            if opt.delete:
                os.remove(p)

    if save_txt or save_img:
        s = f"\n{len(list(save_dir.glob('labels/*.txt')))} labels saved to {save_dir / 'labels'}" if save_txt else ''
        #print(f"Results saved to {save_dir}{s}")

    print(f'Done. ({time.time() - t0:.3f}s)')


if __name__ == '__main__':

    if os.path.isfile('./config.txt'):
        config = configparser.ConfigParser()
        config.read('config.txt')
        
    defaults = {
        'source': config.get('Main', 'source', fallback='input'),
        'dest': config.get('Main', 'dest', fallback='output'),
        'img_size': config.getint('Main', 'img_size', fallback=3264),
        'conf_thres': config.getfloat('Main', 'conf_thres', fallback=0.25),
        'blurratio': config.getint('Main', 'blurratio', fallback=20),
        'rotate': config.getint('Main', 'rotate', fallback=0),
        'limit': config.getint('Main', 'limit', fallback=10),
        'compression': config.getint('Main', 'compression', fallback=60),
        'classes': [0, 1, 2, 3, 5],
        'delete': config.getboolean('Main', 'delete', fallback=False),
        'hidedetarea': config.getboolean('Main', 'hidedetarea', fallback=False),
        'save_org': config.getboolean('Main', 'save_org', fallback=False),
        'save_txt': config.getboolean('Main', 'save_txt', fallback=False),
    }
    
    parser = argparse.ArgumentParser()
    parser.set_defaults(**defaults)
    parser.add_argument('--weights', nargs='+', type=str, default='yolov7.pt', help='model.pt path(s)')
    parser.add_argument('--source', type=str, default=defaults['source'], help='source') 
    parser.add_argument('--dest', default=defaults['dest'], help='results folder name')
    parser.add_argument('--img-size', type=int, default=defaults['img_size'], help='inference size (pixels)')
    parser.add_argument('--conf-thres', type=float, default=defaults['conf_thres'], help='object confidence threshold')
    parser.add_argument('--classes', nargs='+', type=int, default=defaults['classes'], help='filter by class: --class 0, or --class 0 2 3')
    parser.add_argument('--blurratio',type=int,default=defaults['blurratio'], help='blur opacity')
    parser.add_argument('--rotate',type=int, default=defaults['rotate'], help='Rotate clockwise 90, 180, 270')
    parser.add_argument('--limit',type=int, default=defaults['limit'], help='Limit images to process')
    parser.add_argument('--compression',type=int, default=defaults['compression'], help='Compression Value for Output Images')

    parser.add_argument('--iou-thres', type=float, default=0.45, help='IOU threshold for NMS')
    parser.add_argument('--device', default='cpu', help='cuda device, i.e. 0 or 0,1,2,3 or cpu')
    parser.add_argument('--view-img', action='store_true', help='display results')
    parser.add_argument('--save-txt', action='store_true', help='save results to *.txt')
    parser.add_argument('--save-conf', action='store_true', help='save confidences in --save-txt labels')
    parser.add_argument('--nosave', action='store_true', help='do not save images/videos')
    parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true', help='augmented inference')
    parser.add_argument('--update', action='store_true', help='update all models')

    parser.add_argument('--increment-dest', action='store_true', help='increment destination folder')
    parser.add_argument('--hidedetarea',action='store_true', help='Hide Detected Area')
    parser.add_argument('--delete',action='store_true', help='Delete Input Files')
    parser.add_argument('--no-trace', action='store_true', help='don`t trace model')
    opt = parser.parse_args()

    #check_requirements(exclude=('pycocotools', 'thop'))

    if lock_script():
        print(opt)
        with torch.no_grad():
            if opt.update:  # update all models (to fix SourceChangeWarning)
                for opt.weights in ['yolov7.pt']:
                    detect()
                    strip_optimizer(opt.weights)
            else:
                detect()
    # else:
    #     print('detect_and_blur already running')
