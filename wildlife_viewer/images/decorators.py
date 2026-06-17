from django.shortcuts import redirect

def researcher_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')  # Redirect to login page if not authenticated
        
        is_researcher = request.user.groups.filter(
            name="Researcher"
        ).exists()

        if not is_researcher and not request.user.is_superuser:
            return redirect('gallery')  # Redirect to home page if not a researcher

        return view_func(request, *args, **kwargs)
    return wrapper