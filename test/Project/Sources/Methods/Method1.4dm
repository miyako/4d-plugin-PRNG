//%attributes = {}
ARRAY LONGINT:C221($numbers; 0)

For ($i; 1; 100)
	
	APPEND TO ARRAY:C911($numbers; uniform_int_distribution(50000; 100000))
	
End for 