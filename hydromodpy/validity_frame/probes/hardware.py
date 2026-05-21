from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HardwareMetrics:
    cpu_count: int | None = None
    cpu_usage: float | None = None
    cpu_usage_percent: float | None = None
    ram_total_mb: float | None = None
    ram_used_mb: float | None = None
    ram_percent: float | None = None
    gpu_name: str | None = None
    gpu_memory_total_mb: float | None = None
    gpu_memory_used_mb: float | None = None
    gpu_utilization_percent: float | None = None


class HardwareProbe:
    @staticmethod
    def collect() -> HardwareMetrics:
        metrics = HardwareMetrics()
        try:
            import psutil
        except Exception:
            psutil = None  # type: ignore (assignment)

        if psutil is not None:
            metrics.cpu_count = psutil.cpu_count(logical=False)
            metrics.cpu_usage_percent = float(psutil.cpu_percent(interval=None))
            vm = psutil.virtual_memory()
            metrics.ram_total_mb = round(vm.total / (1024 * 1024), 3)
            metrics.ram_used_mb = round(vm.used / (1024 * 1024), 3)
            metrics.ram_percent = float(vm.percent)
        try:
            import pynvml
        except Exception:
            pynvml = None  # type: ignore (assignment)
        if pynvml is not None:
            try:
                pynvml.nvmlInit()
                device_count = pynvml.nvmlDeviceGetCount()
                if device_count > 0:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                    metrics.gpu_name = pynvml.nvmlDeviceGetName(handle).decode("utf-8", "ignore")
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    metrics.gpu_memory_total_mb = round(mem.total / (1024 * 1024), 3)
                    metrics.gpu_memory_used_mb = round(mem.used / (1024 * 1024), 3)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    metrics.gpu_utilization_percent = float(util.gpu)
            except Exception:
                pass
            finally:
                try:
                    pynvml.nvmlShutdown()
                except Exception:
                    pass
        return metrics
