"""Windows peak working set, independent of the accuracy evaluation."""
import ctypes,json,pathlib,subprocess
from ctypes import wintypes
R=pathlib.Path(__file__).resolve().parents[3]
class Memory(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
api=ctypes.WinDLL('psapi').GetProcessMemoryInfo
api.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD];api.restype=wintypes.BOOL
out={}
for name,args in [('no_candidates',['--no-candidates']),('new_candidates_count_fixture',['--word-freq','data/old/word_freq.txt','--char-freq','data/old/dict.txt','--no-index-cache'])]:
    p=subprocess.Popen([str(R/'build/current/text_clean.exe'),*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=R)
    stdout,stderr=p.communicate('薇信\n'.encode());m=Memory();m.cb=ctypes.sizeof(m)
    out[name]=dict(returncode=p.returncode,peak_working_set_bytes=m.PeakWorkingSetSize if api(int(p._handle),ctypes.byref(m),m.cb) else None)
(R/'experiments/E021/results/memory.json').write_text(json.dumps(out,indent=2),encoding='utf8')
