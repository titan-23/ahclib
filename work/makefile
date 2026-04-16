CXX = g++
CXXFLAGS = -O2 -march=native -I./../../../Library_cpp -I. -DLOCAL -fopenmp -g
#  -fsanitize=address
#  -pg
#

OUT = a.out

default:
	@echo "Usage: make <target>"

%: %.cpp
	$(CXX) $(CXXFLAGS) -o $(OUT) $<

clean:
	rm $(OUT)

#
# Info: cnt=471683
