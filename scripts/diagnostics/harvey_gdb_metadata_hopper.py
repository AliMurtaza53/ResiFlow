import re, glob
g="/scratch/akothaw/multimodal_hazard_data/inputs_raw/Harvey_Depths_3m_Final.gdb"
seen=set()
for f in sorted(glob.glob(g+"/*.gdbtable")):
    b=open(f,"rb").read()
    for m in re.finditer(rb"<DERasterDataset.*?</DERasterDataset>", b, re.S):
        x=m.group(0).decode("latin1")
        key=(re.search(r"<CatalogPath>(.*?)</CatalogPath>",x) or [None,""])[1]
        if key in seen: continue
        seen.add(key)
        def t(tag):
            r=re.search(rf"<{tag}>(.*?)</{tag}>",x,re.S); return r.group(1)[:160] if r else None
        print("==",key,"| file",f.split("/")[-1])
        for tag in ["Name","DatasetType","Extent","XMin","XMax","YMin","YMax","PixelType","BandCount","NoDataValue","ColumnCount","RowCount","MeanCellWidth","Statistics","ArcIMSURL","Format","Compression","Description"]:
            v=t(tag)
            if v: print("  ",tag,":",v)
        for u in re.findall(r"UNIT\[\"[^\"]+\",[0-9.]+\]",x)[:2]: print("   unit:",u)
        for k in re.findall(r"<(?:Min|Max|Mean|StdDev|Minimum|Maximum)\w*>[^<]*</\w+>",x)[:8]: print("   stat:",k)
    for m in re.finditer(rb"<metadata.*?</metadata>", b, re.S):
        x=m.group(0).decode("latin1")
        n=re.search(r"<itemName[^>]*>(.*?)</itemName>",x)
        if n and ("Depth" in n.group(1) or "Final" in n.group(1)):
            d=[z for z in re.findall(r"<(?:idAbs|idPurp|supplInf|attrdef|eadetcit|idCredit|useLimit|resConst|Consts)[^>]*>(.*?)</\w+>",x,re.S)]
            print("== metadata for",n.group(1)); 
            for z in d[:6]: print("   ",re.sub(r"<[^>]+>|&lt;[^&]*&gt;|\s+"," ",z)[:400])
