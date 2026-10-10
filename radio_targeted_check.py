import sys,json
from pathlib import Path
import serial
import yac
from modules.find_rad import RadioConnection,_open_serial
def main():
    root=Path.cwd(); records=[]
    def entry(name,result):
        records.append(dict(test=name,result=result)); print(json.dumps(records[-1]),flush=True)
    r=RadioConnection(_open_serial('COM5',115200,serial),'COM5',115200,'CI-V','IC-705','IC-705',civ_address=0xA4)
    def read(c,s=None): return yac._civ_response_data(yac._civ_exchange(r,c,s),0xA4,c,s)
    f=yac._current_frequency(root,r); m=read(4); tones={s:read(0x1B,s) for s in [0,1,2]}; tm=read(0x16,0x5D)
    try:
        assert f and m and all(tones.values()) and tm
        yac._set_frequency(root,r,'en','145.5'); yac._set_mode(r,5)
        for value,target in [('88.5','TX'),('88.5','Both'),('D023','Both'),('D023','TX')]:
            entry('IC-705 '+value+' '+target,yac._set_tone(root,r,'en',value,target))
    finally:
        for s,data in tones.items(): yac._civ_send(r,0x1B,bytes([s])+data)
        yac._civ_send(r,0x16,bytes([0x5D])+tm); yac._set_frequency(root,r,'en',f); yac._civ_send(r,6,m)
        entry('IC-705 restored', all(read(0x1B,s)==data for s,data in tones.items()) and read(0x16,0x5D)==tm and yac._current_frequency(root,r)==f and read(4)==m)
        r.close()
    r=RadioConnection(_open_serial('COM22',38400,serial),'COM22',38400,'CAT','0840','FTX-1')
    try:
        for c in ['ID;','AI;','FA;','FB;','MD0;','MD1;','SM0;','SM1;','SM0;','SM1;','SM0;','SM1;','RM0;','RM1;','RM2;']:
            entry('FTX raw '+c,yac._cat_exchange(r,c))
    finally: r.close()
    (root/'logs'/'radio-targeted-check.json').write_text(json.dumps(records,indent=2))


if __name__ == '__main__':
    main()
