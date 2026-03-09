import zlib
import struct

_E=[0]*512
_L=[0]*256
v=1
for i in range(255):
    _E[i]=v; _L[v]=i
    v=(v<<1)^(0x11D if v&0x80 else 0)
for i in range(255,512):
    _E[i]=_E[i-255]

def _gf_mul(a,b):
    return 0 if not a or not b else _E[(_L[a]+_L[b])%255]

def _poly_mul(p,q):
    r=[0]*(len(p)+len(q)-1)
    for i,a in enumerate(p):
        for j,b in enumerate(q):
            r[i+j]^=_gf_mul(a,b)
    return r

def _rs_gen(n):
    g=[1]
    for i in range(n):
        g=_poly_mul(g,[1,_E[i]])
    return g

def _rs_enc(data,n):
    g=_rs_gen(n)
    m=list(data)+[0]*n
    for i in range(len(data)):
        c=m[i]
        if c:
            for j,v in enumerate(g):
                m[i+j]^=_gf_mul(v,c)
    return m[len(data):]

_VT=[(1,21,19,7),(2,25,34,10),(3,29,55,15),(4,33,80,20),(5,37,108,26)]

_APC={
2:[6,18],
3:[6,22],
4:[6,26],
5:[6,30],
}

def _pick_ver(n):
    for v,s,dc,ec in _VT:
        if 4+8+8*n+4<=dc*8:
            return v,s,dc,ec
    raise ValueError

def _fmt(mask):
    d=(0b01<<3)|mask
    r=d<<10
    for i in range(4,-1,-1):
        if r&(1<<(i+10)):
            r^=0x537<<i
    return ((d<<10)|r)^0x5412

def _build(ver,size):
    M=[[0]*size for _ in range(size)]
    F=[[False]*size for _ in range(size)]

    def sf(r,c,v):
        if 0<=r<size and 0<=c<size:
            M[r][c]=int(bool(v))
            F[r][c]=True

    def finder(tr,tc):
        for r in range(7):
            for c in range(7):
                sf(tr+r,tc+c,r in (0,6) or c in (0,6) or 2<=r<=4 and 2<=c<=4)

    finder(0,0)
    finder(0,size-7)
    finder(size-7,0)

    for i in range(8):
        sf(7,i,0); sf(i,7,0)
        sf(7,size-1-i,0); sf(i,size-8,0)
        sf(size-8,i,0); sf(size-1-i,7,0)

    for i in range(7,size-7):
        if not F[6][i]: sf(6,i,i%2==0)
        if not F[i][6]: sf(i,6,i%2==0)

    if ver>=2:
        centers=_APC[ver]
        for r in centers:
            for c in centers:
                if F[r][c]: continue
                for dr in range(-2,3):
                    for dc in range(-2,3):
                        sf(r+dr,c+dc,abs(dr)==2 or abs(dc)==2 or (dr==0 and dc==0))

    sf(4*ver+9,8,1)

    for r,c in [(8,i) for i in range(9)]+[(i,8) for i in range(9)]:
        F[r][c]=True
    for i in range(8):
        F[8][size-1-i]=True
        F[size-1-i][8]=True

    return M,F

def _write_fmt(M,size,mask):
    b=_fmt(mask)
    fmt=[(b>>i)&1 for i in range(14,-1,-1)]

    tl=[(8,0),(8,1),(8,2),(8,3),(8,4),(8,5),(8,7),(8,8),
        (7,8),(5,8),(4,8),(3,8),(2,8),(1,8),(0,8)]

    for i,(r,c) in enumerate(tl):
        M[r][c]=fmt[i]

    for i in range(8):
        M[8][size-1-i]=fmt[i]

    for i in range(7):
        M[size-7+i][8]=fmt[8+i]

def _encode(text,dc):
    data=text.encode()
    n=len(data)
    bits=[0,1,0,0]
    for i in range(7,-1,-1):
        bits.append((n>>i)&1)
    for b in data:
        for i in range(7,-1,-1):
            bits.append((b>>i)&1)
    for _ in range(min(4,dc*8-len(bits))):
        bits.append(0)
    while len(bits)%8:
        bits.append(0)
    pad=[0xEC,0x11]
    pi=0
    while len(bits)<dc*8:
        for i in range(7,-1,-1):
            bits.append((pad[pi%2]>>i)&1)
        pi+=1
    return [sum(bits[i+j]<<(7-j) for j in range(8)) for i in range(0,dc*8,8)]

def _place(M,F,size,cw,ec):
    bits=[]
    for b in cw+ec:
        for i in range(7,-1,-1):
            bits.append((b>>i)&1)
    idx=0
    up=True
    col=size-1
    while col>=0:
        if col==6:
            col-=1
            continue
        rows=range(size-1,-1,-1) if up else range(size)
        for r in rows:
            for c in [col,col-1]:
                if 0<=c<size and not F[r][c] and idx<len(bits):
                    M[r][c]=bits[idx]
                    idx+=1
        up=not up
        col-=2

_MF=[
lambda r,c:(r+c)%2==0,
lambda r,c:r%2==0,
lambda r,c:c%3==0,
lambda r,c:(r+c)%3==0,
lambda r,c:(r//2+c//3)%2==0,
lambda r,c:(r*c)%2+(r*c)%3==0,
lambda r,c:((r*c)%2+(r*c)%3)%2==0,
lambda r,c:((r+c)%2+(r*c)%3)%2==0,
]

def _apply_mask(M,F,size,p):
    R=[row[:] for row in M]
    fn=_MF[p]
    for r in range(size):
        for c in range(size):
            if not F[r][c] and fn(r,c):
                R[r][c]^=1
    return R

def _penalty(M,size):
    s=0
    lines=M+[[M[r][c] for r in range(size)] for c in range(size)]
    for line in lines:
        cnt=1
        for i in range(1,size):
            if line[i]==line[i-1]:
                cnt+=1
            else:
                if cnt>=5:
                    s+=cnt-2
                cnt=1
        if cnt>=5:
            s+=cnt-2
    for r in range(size-1):
        for c in range(size-1):
            v=M[r][c]
            if M[r][c+1]==v and M[r+1][c]==v and M[r+1][c+1]==v:
                s+=3
    p1=[1,0,1,1,1,0,1,0,0,0,0]
    p2=[0,0,0,0,1,0,1,1,1,0,1]
    for line in lines:
        for i in range(size-10):
            if line[i:i+11]==p1 or line[i:i+11]==p2:
                s+=40
    dark=sum(M[r][c] for r in range(size) for c in range(size))
    s+=abs(dark*100//(size*size)-50)//5*10
    return s

def _best_mask(M,F,size):
    best=None
    bm=None
    for p in range(8):
        masked=_apply_mask(M,F,size,p)
        _write_fmt(masked,size,p)
        sc=_penalty(masked,size)
        if best is None or sc<best:
            best=sc
            bm=masked
    return bm

def _make_final(text):
    raw=text.encode()
    ver,size,dc,n_ec=_pick_ver(len(raw))
    cw=_encode(text,dc)
    ec=_rs_enc(cw,n_ec)
    M,F=_build(ver,size)
    _place(M,F,size,cw,ec)
    return _best_mask(M,F,size),size

def normalize_url(u):
    return u

def qr_png(text,scale=10,margin=4):
    text=normalize_url(text)
    final,size=_make_final(text)
    total=(size+2*margin)*scale
    raw=bytearray()
    for r in range(total):
        raw.append(0)
        qr_row=r//scale-margin
        for c in range(total):
            qr_col=c//scale-margin
            if 0<=qr_row<size and 0<=qr_col<size and final[qr_row][qr_col]:
                raw.append(0)
            else:
                raw.append(255)
    comp=zlib.compress(bytes(raw),9)
    def chunk(name,data):
        c=name+data
        return struct.pack(">I",len(data))+c+struct.pack(">I",zlib.crc32(c)&0xffffffff)
    return (
        b'\x89PNG\r\n\x1a\n'+
        chunk(b'IHDR',struct.pack(">IIBBBBB",total,total,8,0,0,0,0))+
        chunk(b'IDAT',comp)+
        chunk(b'IEND',b'')
    )