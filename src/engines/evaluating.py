import os
import torch
import json
import numpy as np
from tqdm import tqdm
from pycocotools.mask import encode
from torchvision.ops import box_convert
from torch.utils.tensorboard import SummaryWriter

from src.evaluator.evaluator import Evaluator



def evaluate_one_epoch(model, loader, cocoGT, predPath, tb_writer: SummaryWriter = None, epoch = 1):
    model.eval()
    device = model.device

    box_results, mask_results = dict(), dict()
    box_results["res"], mask_results["res"] = [], []

    with torch.no_grad():
        pbar = tqdm(loader, desc=f"Validating epoch {epoch}")
        for _, target in enumerate(pbar, start=1):
            images, targets = target
            img_ids = [elem["image_id"] for elem in targets]
            del targets

            #* --------------- Forward Pass ----------------
            images = list([image.to(device) for image in images])
            pred = model(images)

            #* --------------- Create Prediction File ----------------
            for i, elem in enumerate(pred):
                for idx, bbox in enumerate(elem["boxes"]):
                   box_results["res"].append({
                          "image_id": img_ids[i].item(),
                          "category_id": elem["labels"][idx].item(),
                          "bbox": [round(elem, 2) for elem in box_convert(bbox, "xyxy", "xywh").tolist()],
                          "score": round(elem["scores"][idx].item(), 2)
                     })

                masks = elem["masks"].squeeze(1)
                for idx, mask in enumerate(masks):
                    toMean = mask[torch.where(mask > 0.0)]
                    score = torch.mean(toMean).item()
                    mask = encode(np.asfortranarray((mask > 0.5).cpu().numpy()))
                    mask["counts"] = mask["counts"].decode("utf-8")

                    mask_results["res"].append({
                        "image_id": img_ids[i].item(),
                        "category_id": elem["labels"][idx].item(),
                        "segmentation": mask,
                        "score": round(score, 2)
                    })
            # torch.cuda.empty_cache()

        #* --------------- Save Prediction File ----------------

        output_box_path = predPath.replace("results", "box_results")
        output_mask_path = predPath.replace("results", "mask_results")

        output_box = [elem for elem in box_results["res"]]
        output_mask = [elem for elem in mask_results["res"]]
        with open(output_box_path, "w") as f:
            json.dump(output_box, f)
        with open(output_mask_path, "w") as f:
            json.dump(output_mask, f)

        del box_results, mask_results
        del output_box, output_mask

        #* --------------- Evaluate ----------------
        evaluator = Evaluator(cocoGT, output_box_path, output_mask_path)
        bbox_map, segm_map = evaluator.compute_map()

        #* --------------- Log mAP ----------------

        if tb_writer is not None:
            maps = {
                "bbox_map": bbox_map[0],
                "segm_map": segm_map[0]
            }
            tb_writer.add_scalars("val/map", maps, epoch)

        print("[Validation] Epoch: {:03d} Segmentation mAP: {:.2f}, Bounding Box mAP: {:.2f}".format(epoch, segm_map[0], bbox_map[0]))
        print()
    return bbox_map[0], segm_map[0]
