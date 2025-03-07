import math
import numpy as np
import multiprocessing


class Quantizer:

    def __init__(self,
                 tensor_list,
                 worker_num=1,
                 debug=False):
        self._tensor_list = tensor_list
        self._worker_num = worker_num
        self._debug = debug

        self._bits = {}
        self._quantized_flag = False

    @property
    def bits(self):
        assert self._quantized_flag, "Please use quantize() first."
        return self._bits

    def quantize(self, distributions, distribution_intervals):

        if self._debug and self._quantized_flag:
            return

        self._quantized_flag = True
        pool = multiprocessing.Pool(processes=self._worker_num)
        amount_per_worker = int(math.floor(len(self._tensor_list) / self._worker_num))
        results = []

        for worker_i in range(self._worker_num):
            sub_tensor_list = self._tensor_list[worker_i * amount_per_worker:
                                                (worker_i + 1) * amount_per_worker]
            if worker_i == 0:
                sub_tensor_list += self._tensor_list[self._worker_num * amount_per_worker:]
            sub_distributions, sub_distribution_intervals = {}, {}
            for tensor_name in sub_tensor_list:
                sub_distributions[tensor_name] = distributions[tensor_name]
                sub_distribution_intervals[tensor_name] = distribution_intervals[tensor_name]
            result = pool.apply_async(
                run,
                args=(Quantizer,
                      sub_tensor_list,
                      sub_distributions,
                      sub_distribution_intervals,
                      self._debug))
            results.append(result)
        pool.close()
        pool.join()
        for result in results:
            tensor_list, sub_bits = result.get()
            for (tensor_name, bit) in zip(tensor_list, sub_bits):
                self._bits[tensor_name] = bit
        pool.terminate()

    @staticmethod
    def quantize_worker(tensor_list, distributions, intervals, debug=False):
        if debug:
            return tensor_list, [1 for _ in range(len(tensor_list))]
        bits = []
        for tensor_name in tensor_list:
            distribution = Quantizer.normalize_distribution(distributions[tensor_name])
            threshold_bin = Quantizer.threshold_distribution(distribution)
            threshold_bias = (threshold_bin + 0.5) * intervals[tensor_name]

            bit_int_d = math.ceil(math.log(threshold_bias, 2))
            bit_bra_d_8 = int(8 - 1 - bit_int_d)
            bits.append(bit_bra_d_8)
            print('{} '.format(tensor_name), 'bit:', bit_bra_d_8)
        return tensor_list, bits

    @staticmethod
    def normalize_distribution(distribution):
        return distribution.astype(np.float32) / (distribution.sum() + 1e-12)

    @staticmethod
    def threshold_distribution(distribution, target_bin=128):
        min_kl_divergence = 66666
        threshold_sum = distribution[target_bin:].sum()
        target_threshold = distribution.size - 1

        for threshold in range(target_bin, distribution.size):
            t_distribution = list(distribution[:threshold])
            t_distribution[threshold - 1] += threshold_sum
            threshold_sum = threshold_sum - distribution[threshold]

            quantize_distribution = [0. for _ in range(target_bin)]
            expand_distribution = [1e-9 for _ in range(threshold)]
            num_per_bin = threshold / target_bin

            #get quantized distribution
            for i in range(0, target_bin):
                start = i * num_per_bin
                end = start + num_per_bin
                left_upper = int(math.ceil(start))
                if left_upper > start:
                    left_scale = left_upper - start
                    quantize_distribution[i] += left_scale * distribution[left_upper - 1]
                right_lower = int(math.floor(end))
                if right_lower < end:
                    right_scale = end - right_lower
                    quantize_distribution[i] += right_scale * distribution[right_lower]

                quantize_distribution[i] += distribution[left_upper:right_lower].sum()

            # get dequantize_distribution
            for i in range(0, target_bin):
                start = i * num_per_bin
                end = start + num_per_bin
                count = 0

                left_upper = int(math.ceil(start))
                left_scale = 0.0
                if left_upper > start:
                    left_scale = left_upper - start
                    if distribution[left_upper - 1] != 0:
                        count += left_scale

                right_lower = int(math.floor(end))
                right_scale = 0.0
                if right_lower < end:
                    right_scale = end - right_lower
                    if distribution[right_lower] != 0:
                        count += right_scale

                for j in range(left_upper, right_lower):
                    if distribution[j] != 0:
                        count = count + 1
                expand_value = quantize_distribution[i] / count

                if left_upper > start:
                    if distribution[left_upper - 1] != 0:
                        expand_distribution[left_upper - 1] += expand_value * left_scale
                if right_lower < end:
                    if distribution[right_lower] != 0:
                        expand_distribution[right_lower] += expand_value * right_scale
                for j in range(left_upper, right_lower):
                    if distribution[j] != 0:
                        expand_distribution[j] += expand_value

            # compute the kl_divergence between quantized distribution and dequantize_distribution
            kl_divergence = Quantizer.compute_kl_divergence(t_distribution, expand_distribution)
            if kl_divergence < min_kl_divergence:
                min_kl_divergence = kl_divergence
                target_threshold = threshold

        return target_threshold

    @staticmethod
    def compute_kl_divergence(dist_a, dist_b):
        dist_a = np.array(dist_a)
        dist_b = np.array(dist_b)
        nonzero_inds = dist_a != 0
        return np.sum(dist_a[nonzero_inds] * np.log(dist_a[nonzero_inds] / dist_b[nonzero_inds]))


def run(cls_instance, *args):
    """Compatible with Python2."""
    return cls_instance.quantize_worker(*args)
