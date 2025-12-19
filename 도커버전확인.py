# main.py에 추가
print("=== 처음 5개 요청 ===")
for r in requests[:5]:
    print(f"{r.id}: t={r.t_req}, o=({r.o_lon:.6f}, {r.o_lat:.6f})")