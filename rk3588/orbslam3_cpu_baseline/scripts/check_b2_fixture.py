"""Independent design-rule checks on C++ output, including tie/border cases."""
import csv,json,math,pathlib,sys

def check(root):
    root=pathlib.Path(root)
    def rows(name):
        with (root/name).open() as f:return list(csv.DictReader(f))
    angles=rows('angles.csv')
    for r in angles:
        n=int(r['bins']);a=float(r['angle']);step=360/n
        # Nearest circular bin; midpoint ties round forward, not Python banker's rounding.
        expected=((math.floor(a/step+0.5))%n)*step
        assert abs(float(r['quantized'])-expected)<1e-5,(r,expected)
    grids=rows('grid.csv')
    for case in range(4):
        budget=3 if case==1 else 17;side=math.isqrt((23*19)//budget)
        cols,lines=23//side,19//side
        points=[(x,y,(x*7+y*3)%13) for y in range(19) for x in range(23)
                if case!=3 and (case!=2 or (x==22 and y==18))]
        chosen=[];empty=0
        for gy in range(lines):
            for gx in range(cols):
                members=[p for p in points if min(p[0]//side,cols-1)==gx and min(p[1]//side,lines-1)==gy]
                if members:chosen.append(min(members,key=lambda p:(-p[2],p[1],p[0])))
                else:empty+=1
        if len(chosen)>budget:chosen=sorted(chosen,key=lambda p:(-p[2],p[1],p[0]))[:budget]
        records=[r for r in grids if int(r['case_id'])==case]
        observed=[tuple(int(float(r[k])) for k in ('x','y','response')) for r in records if int(r['selected'])]
        assert observed==chosen,(case,observed,chosen)
        for r in records:
            assert (int(r['side']),int(r['cols']),int(r['rows']),int(r['empty']),int(r['shortfall']))==(side,cols,lines,empty,budget-len(chosen))
    for r in rows('box.csv'):
        y,x=int(r['y'])*2,int(r['x'])*2
        values=[((y+j)*19+(x+i)*29+(y+j)*(x+i)*7)%256 for j in range(2) for i in range(2)]
        expected=(sum(values)+(2 if int(r['rounding']) else 0))//4
        assert int(r['value'])==expected,(r,expected)
    budgets=rows('budgets.csv')
    for n in (1000,5000):
        for levels in (1,2,8):
            group=[r for r in budgets if int(r['n'])==n and int(r['levels'])==levels]
            assert sum(int(r['budget']) for r in group)==n
            if levels==2:assert [int(r['budget']) for r in group]==([667,333] if n==1000 else [3333,1667])
    facts=dict(status='PASS',angles=len(angles),grid_cases=4,box_samples=len(rows('box.csv')),budget_cases=6)
    (root/'independent_check.json').write_text(json.dumps(facts,indent=2))
    print('INDEPENDENT_CANDIDATE_CHECK '+json.dumps(facts))
if __name__=='__main__':check(sys.argv[1])
