from rest_framework import serializers

class OptimizeRouteSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200)
    finish = serializers.CharField(max_length=200)
    max_range_miles = serializers.FloatField(default=500, min_value=50, max_value=500)
    mpg = serializers.FloatField(default=10, min_value=1, max_value=100)
    station_corridor_miles = serializers.FloatField(default=15, min_value=1, max_value=50)
