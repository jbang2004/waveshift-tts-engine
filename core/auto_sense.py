import logging
import os
import importlib.util
import sys
import torch
import numpy as np
from tqdm import tqdm
from pathlib import Path
import time
from funasr.register import tables
from funasr.auto.auto_model import AutoModel as BaseAutoModel
from funasr.auto.auto_model import prepare_data_iterator
from funasr.utils.misc import deep_update
from funasr.models.campplus.utils import sv_chunk, postprocess
from funasr.models.campplus.cluster_backend import ClusterBackend
from .sentence_tools import get_sentences
from funasr.utils.vad_utils import slice_padding_audio_samples
from funasr.utils.load_utils import load_audio_text_image_video

class SenseAutoModel(BaseAutoModel):
    def __init__(self, config, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)
        self.config = config
        
        if self.spk_model is not None:
            self.cb_model = ClusterBackend().to(kwargs["device"])
            spk_mode = kwargs.get("spk_mode", "punc_segment")
            if spk_mode not in ["default", "vad_segment", "punc_segment"]:
                self.logger.error("spk_mode 应该是 'default', 'vad_segment' 或 'punc_segment' 之一。")
            self.spk_mode = spk_mode

    def run_vad(self, input, input_len=None, **cfg):
        """调用VAD模型进行推断并返回结果"""
        # 更新VAD配置并执行VAD推断
        deep_update(self.vad_kwargs, cfg)
        return self.inference(input, input_len=input_len, model=self.vad_model, kwargs=self.vad_kwargs, **cfg)

    def inference_with_vad(self, input, input_len=None, task_id=None, task_paths=None, **cfg):
        kwargs = self.kwargs
        self.tokenizer = kwargs.get("tokenizer")
        results = None # Initialize
        spk_res = None # Initialize
        results_ret_list = []
        
        try:
            # 调用独立的 VAD 推断
            res = self.run_vad(input, input_len=input_len, **cfg)
            model = self.model
            deep_update(kwargs, cfg)
            kwargs["batch_size"] = max(int(kwargs.get("batch_size_s", 300)) * 1000, 1)
            batch_size_threshold_ms = int(kwargs.get("batch_size_threshold_s", 60)) * 1000

            # 获取输入数据列表，丢弃 key_list
            _, data_list = prepare_data_iterator(input, input_len=input_len, data_type=kwargs.get("data_type", None))

            pbar_total = tqdm(total=len(res), dynamic_ncols=True, disable=kwargs.get("disable_pbar", False))

            for i, item in enumerate(res):
                try:
                    # 获取 VAD 分段结果
                    vadsegments = item["value"]
                    input_i = data_list[i]
                    fs = kwargs["frontend"].fs if hasattr(kwargs["frontend"], "fs") else 16000
                    speech = load_audio_text_image_video(input_i, fs=fs, audio_fs=kwargs.get("fs", 16000))
                    speech_lengths = len(speech)
                    self.logger.debug(f"音频长度: {speech_lengths} 样本")

                    if speech_lengths < 400:
                        self.logger.warning(f"音频太短（{speech_lengths} 样本），可能导致处理错误")

                    sorted_data = sorted([(seg, idx) for idx, seg in enumerate(vadsegments)], key=lambda x: x[0][1] - x[0][0])
                    if not sorted_data:
                        self.logger.info(f"解码，第 {i} 条，空语音")
                        continue

                    results_sorted = []
                    all_segments = []
                    beg_idx, end_idx = 0, 1
                    max_len_in_batch = 0

                    for j in range(len(sorted_data)):
                        sample_length = sorted_data[j][0][1] - sorted_data[j][0][0]
                        potential_batch_length = max(max_len_in_batch, sample_length) * (j + 1 - beg_idx)

                        if (j < len(sorted_data) - 1 and 
                            sample_length < batch_size_threshold_ms and 
                            potential_batch_length < kwargs["batch_size"]):
                            max_len_in_batch = max(max_len_in_batch, sample_length)
                            end_idx += 1
                            continue

                        speech_j, _ = slice_padding_audio_samples(speech, speech_lengths, sorted_data[beg_idx:end_idx])
                        results = self.inference(speech_j, input_len=None, model=model, kwargs=kwargs, **cfg)

                        if self.spk_model is not None:
                            for _b, speech_segment in enumerate(speech_j):
                                vad_segment = sorted_data[beg_idx:end_idx][_b][0]
                                segments = sv_chunk([[vad_segment[0] / 1000.0, vad_segment[1] / 1000.0, np.array(speech_segment)]])
                                all_segments.extend(segments)
                                speech_b = [seg[2] for seg in segments]
                                spk_res = self.inference(speech_b, input_len=None, model=self.spk_model, kwargs=kwargs, **cfg)
                                results[_b]["spk_embedding"] = spk_res[0]["spk_embedding"]
                        beg_idx, end_idx = end_idx, end_idx + 1
                        max_len_in_batch = sample_length
                        results_sorted.extend(results)

                        # --- Memory cleanup for loop iteration ---
                        del speech_j # Delete audio batch
                        if results is not None: del results
                        if self.spk_model is not None and spk_res is not None: del spk_res
                        # --- End Memory cleanup ---

                    if len(results_sorted) != len(sorted_data):
                        self.logger.info(f"解码，第 {i} 条，空结果")
                        continue

                    restored_data = [0] * len(sorted_data)
                    for j, (_, idx) in enumerate(sorted_data):
                        restored_data[idx] = results_sorted[j]

                    result = self.combine_results(restored_data, vadsegments)

                    if self.spk_model is not None and kwargs.get("return_spk_res", True):
                        all_segments.sort(key=lambda x: x[0])
                        spk_embedding = result["spk_embedding"]
                        labels = self.cb_model(spk_embedding.cpu(), oracle_num=kwargs.get("preset_spk_num", None))
                        sv_output = postprocess(all_segments, None, labels, spk_embedding.cpu())

                        if "timestamp" not in result:
                            self.logger.error("speaker diarization 依赖于时间戳")
                            sentence_list = []
                        else:
                            # 传递显式参数给get_sentences
                            sentence_list = get_sentences(
                                tokens=result["token"],
                                timestamps=result["timestamp"],
                                tokenizer=self.tokenizer,
                                speech=speech,
                                sd_time_list=sv_output,
                                sample_rate=fs,
                                config=self.config,
                                task_id=task_id,
                                task_paths=task_paths
                            )
                            results_ret_list = sentence_list
                    else:
                        sentence_list = []
                    pbar_total.update(1)

                except Exception as e:
                    self.logger.error(f"处理项目 {i} 失败: {e}")

            pbar_total.close()
            return results_ret_list
            
        finally:
            # 简化为关注最关键的大对象清理
            large_variables = ['speech', 'result', 'spk_embedding', 'labels', 'sv_output']
            for var_name in large_variables:
                if var_name in locals() and locals()[var_name] is not None:
                    del locals()[var_name]

            # GPU缓存清理保持不变
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def combine_results(self, restored_data, vadsegments):
        result = {}
        for j, data in enumerate(restored_data):
            for k, v in data.items():
                if k.startswith("timestamp"):
                    if k not in result:
                        result[k] = []
                    for t in v:
                        t[0] += vadsegments[j][0]
                        t[1] += vadsegments[j][0]
                    result[k].extend(v)
                elif k == "spk_embedding":
                    if k not in result:
                        result[k] = v
                    else:
                        result[k] = torch.cat([result[k], v], dim=0)
                elif "token" in k:
                    if k not in result:
                        result[k] = v
                    else:
                        result[k].extend(v)
                else:
                    if k not in result:
                        result[k] = v
                    else:
                        result[k] += v
        return result
