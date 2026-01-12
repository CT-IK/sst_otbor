n = int(input())
path = input().strip()

x = y = 0
visited = {(0, 0)}

for move in path:
    if move == 'L':
        x -= 1
    elif move == 'R':
        x += 1
    elif move == 'U':
        y += 1
    elif move == 'D':
        y -= 1

    if (x, y) in visited:
        print("YES")
        break

    visited.add((x, y))
else:
    print("NO")



